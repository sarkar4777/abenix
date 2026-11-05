// Abenix edge runtime in Rust, one binary that serves :8080, takes bundles over HTTP and MQTT,
// checks their signatures and calls the model on request.

use std::collections::{BTreeMap, HashSet};
use std::io::{Cursor, Read};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{anyhow, Context, Result};
use axum::{
    extract::{DefaultBodyLimit, Path as AxPath, Request, State},
    http::{header, HeaderMap, StatusCode},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use bytes::Bytes;
use once_cell::sync::Lazy;
use rsa::pkcs8::DecodePublicKey;
use rsa::pss::{Signature, VerifyingKey};
use rsa::signature::Verifier;
use rsa::RsaPublicKey;
use rumqttc::{AsyncClient, Event, Incoming, MqttOptions, QoS};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tokio::sync::RwLock;
use tracing::{error, info, warn};

pub static EDGE_SAFE_TOOLS: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    [
        "mqtt_publish",
        "mqtt_subscribe",
        "current_time",
        "windowed_state",
        "connector_call",
        "code_executor",
    ]
    .into_iter()
    .collect()
});

pub const MAX_BUNDLE_BYTES: usize = 16 * 1024 * 1024;
pub const MAX_BUNDLE_MEMBERS: usize = 256;
pub const CODE_TIMEOUT_SECONDS: u64 = 5;
pub const CODE_OUTPUT_BYTES: usize = 64 * 1024;
pub const SAVED_BUNDLE: &str = "bundle.agent";
const OAUTH_BETA: &str = "oauth-2025-04-20";

pub fn deploy_topic(gateway_id: &str, slug: &str) -> String {
    format!("edge/{gateway_id}/deploy/{slug}")
}

pub fn ack_topic(gateway_id: &str, slug: &str) -> String {
    format!("edge/{gateway_id}/ack/{slug}")
}

#[derive(Clone, Debug)]
pub struct Config {
    pub gateway_id: String,
    pub gateway_name: String,
    pub platform_url: String,
    pub platform_token: String,
    pub mqtt_url: String,
    pub signing_pubkey_pem: String,
    pub signing_pubkey_path: PathBuf,
    pub bundle_dir: PathBuf,
    pub endpoint_url: String,
    pub anthropic_api_key: String,
    pub anthropic_auth_token: String,
    pub anthropic_base_url: String,
    pub port: u16,
    pub auth_token: String,
    pub allow_unsigned: bool,
    pub allow_no_auth: bool,
    pub code_enabled: bool,
    pub tenant_id: String,
}

fn env_is_true(key: &str) -> bool {
    std::env::var(key).map(|v| v.trim() == "true").unwrap_or(false)
}

impl Config {
    // for tests, leaves the process environment alone
    pub fn for_test(bundle_dir: PathBuf, signing_pubkey_path: PathBuf, gateway_id: String) -> Self {
        let _ = std::fs::create_dir_all(&bundle_dir);
        Self {
            gateway_name: gateway_id.clone(),
            gateway_id,
            platform_url: String::new(),
            platform_token: String::new(),
            mqtt_url: String::new(),
            signing_pubkey_pem: String::new(),
            signing_pubkey_path,
            bundle_dir,
            endpoint_url: String::new(),
            anthropic_api_key: String::new(),
            anthropic_auth_token: String::new(),
            anthropic_base_url: "https://api.anthropic.com".into(),
            port: 0,
            auth_token: "test-token".into(),
            allow_unsigned: false,
            allow_no_auth: false,
            code_enabled: false,
            tenant_id: String::new(),
        }
    }

    pub fn from_env() -> Self {
        let bundle_dir = PathBuf::from(
            std::env::var("BUNDLE_DIR").unwrap_or_else(|_| "/var/edge/agents".into()),
        );
        let _ = std::fs::create_dir_all(&bundle_dir);
        let gateway_id = std::env::var("GATEWAY_ID").unwrap_or_else(|_| "edge-local".into());
        Self {
            gateway_name: std::env::var("GATEWAY_NAME").unwrap_or_else(|_| gateway_id.clone()),
            gateway_id,
            platform_url: std::env::var("PLATFORM_URL")
                .unwrap_or_else(|_| "http://host.docker.internal:8000".into()),
            platform_token: std::env::var("PLATFORM_TOKEN").unwrap_or_default(),
            mqtt_url: std::env::var("MQTT_URL").unwrap_or_default(),
            signing_pubkey_pem: std::env::var("SIGNING_PUBKEY_PEM").unwrap_or_default(),
            signing_pubkey_path: PathBuf::from(
                std::env::var("SIGNING_PUBKEY_PATH")
                    .unwrap_or_else(|_| "/etc/edge/signing_pub.pem".into()),
            ),
            bundle_dir,
            endpoint_url: std::env::var("ENDPOINT_URL").unwrap_or_default(),
            anthropic_api_key: std::env::var("ANTHROPIC_API_KEY")
                .unwrap_or_default()
                .trim()
                .to_string(),
            anthropic_auth_token: std::env::var("ANTHROPIC_AUTH_TOKEN")
                .ok()
                .filter(|v| !v.trim().is_empty())
                .or_else(|| std::env::var("CLAUDE_SUBSCRIPTION_TOKEN").ok())
                .unwrap_or_default()
                .trim()
                .to_string(),
            anthropic_base_url: std::env::var("ANTHROPIC_BASE_URL")
                .unwrap_or_else(|_| "https://api.anthropic.com".into()),
            port: std::env::var("PORT")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(8080),
            auth_token: std::env::var("EDGE_AUTH_TOKEN")
                .unwrap_or_default()
                .trim()
                .to_string(),
            allow_unsigned: env_is_true("EDGE_ALLOW_UNSIGNED"),
            allow_no_auth: env_is_true("EDGE_ALLOW_NO_AUTH"),
            code_enabled: env_is_true("EDGE_ENABLE_CODE_EXECUTOR"),
            tenant_id: std::env::var("TENANT_ID")
                .unwrap_or_default()
                .trim()
                .to_string(),
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum BundleError {
    #[error("{0}")]
    Msg(String),
}

impl BundleError {
    pub fn new(s: impl Into<String>) -> Self {
        BundleError::Msg(s.into())
    }
}

pub fn load_pubkey(cfg: &Config) -> Result<Option<RsaPublicKey>> {
    let pem = if !cfg.signing_pubkey_pem.is_empty() {
        cfg.signing_pubkey_pem.clone()
    } else if cfg.signing_pubkey_path.exists() {
        std::fs::read_to_string(&cfg.signing_pubkey_path).unwrap_or_default()
    } else {
        String::new()
    };
    if pem.trim().is_empty() {
        return Ok(None);
    }
    let key = RsaPublicKey::from_public_key_pem(&pem)
        .with_context(|| "failed to parse signing pubkey")?;
    Ok(Some(key))
}

// the same refusals as the Python runtime, a gateway that cannot verify or authenticate does not start
pub fn check_startup(cfg: &Config) -> Result<()> {
    let pubkey = load_pubkey(cfg)?;
    if cfg.allow_unsigned {
        warn!("EDGE_ALLOW_UNSIGNED=true, unsigned bundles will be accepted, development only");
    } else if pubkey.is_none() {
        return Err(anyhow!(
            "edge-runtime refused to start, no signing public key. Set SIGNING_PUBKEY_PEM or mount it at SIGNING_PUBKEY_PATH ({}). Fetch it from GET /api/edge/signing-key on the platform. EDGE_ALLOW_UNSIGNED=true bypasses this for local development only.",
            cfg.signing_pubkey_path.display()
        ));
    }
    if cfg.allow_no_auth {
        warn!("EDGE_ALLOW_NO_AUTH=true, anyone who can reach this port can install and run agents, development only");
    } else if cfg.auth_token.is_empty() {
        return Err(anyhow!(
            "edge-runtime refused to start, no EDGE_AUTH_TOKEN. Set it so bundle install and execute need a bearer token. EDGE_ALLOW_NO_AUTH=true bypasses this for local development only."
        ));
    }
    if cfg.code_enabled {
        warn!("EDGE_ENABLE_CODE_EXECUTOR=true, params.code runs for agents that list code_executor");
    }
    if !cfg.tenant_id.is_empty() {
        info!(tenant_id = %cfg.tenant_id, "tenant_binding");
    }
    Ok(())
}

pub fn valid_slug(slug: &str) -> bool {
    let mut chars = slug.chars();
    let first_ok = chars.next().map(|c| c.is_ascii_alphanumeric()).unwrap_or(false);
    first_ok
        && slug.len() <= 95
        && !slug.contains("..")
        && slug
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-'))
}

fn safe_member_path(path: &str) -> bool {
    !path.is_empty()
        && !path.starts_with('/')
        && !path.contains('\\')
        && !path.split('/').any(|seg| seg == "..")
}

// plain files and folders under safe relative names only, anything else refuses the bundle
pub fn read_tar_members(
    bundle: &[u8],
) -> Result<(Vec<(String, Vec<u8>, u64, u32)>, Option<Vec<u8>>)> {
    if bundle.len() > MAX_BUNDLE_BYTES {
        return Err(anyhow!(BundleError::new(format!(
            "bundle is over {MAX_BUNDLE_BYTES} bytes"
        ))));
    }
    let mut archive = tar::Archive::new(Cursor::new(bundle));
    let mut members: Vec<(String, Vec<u8>, u64, u32)> = Vec::new();
    let mut sig: Option<Vec<u8>> = None;
    let mut seen: HashSet<String> = HashSet::new();
    for entry in archive.entries()? {
        let mut e = entry?;
        let path = e.path()?.to_string_lossy().into_owned();
        let kind = e.header().entry_type();
        if !kind.is_file() && !kind.is_dir() {
            return Err(anyhow!(BundleError::new(format!(
                "bundle entry {path} is a link or device, refused"
            ))));
        }
        if !safe_member_path(&path) {
            return Err(anyhow!(BundleError::new(format!(
                "unsafe path in bundle {path}"
            ))));
        }
        if !seen.insert(path.clone()) {
            return Err(anyhow!(BundleError::new(format!(
                "duplicate entry in bundle {path}"
            ))));
        }
        if seen.len() > MAX_BUNDLE_MEMBERS {
            return Err(anyhow!(BundleError::new("bundle has too many entries")));
        }
        let mtime = e.header().mtime().unwrap_or(0);
        let mode = e.header().mode().unwrap_or(0o644);
        let mut buf = Vec::new();
        e.read_to_end(&mut buf)?;
        if path == "signature.sig" {
            sig = Some(buf);
        } else {
            members.push((path, buf, mtime, mode));
        }
    }
    Ok((members, sig))
}

// rebuild the tar without signature.sig so digest matches what python signed.
pub fn rebuild_tar(members: &[(String, Vec<u8>, u64, u32)]) -> Result<Vec<u8>> {
    let mut buf = Vec::new();
    {
        let mut builder = tar::Builder::new(&mut buf);
        for (name, data, mtime, mode) in members {
            let mut header = tar::Header::new_ustar();
            header.set_size(data.len() as u64);
            header.set_mtime(*mtime);
            let m = if *mode == 0 { 0o644 } else { *mode };
            header.set_mode(m);
            header.set_entry_type(tar::EntryType::Regular);
            header.set_cksum();
            builder.append_data(&mut header, name, &data[..])?;
        }
        builder.finish()?;
    }
    Ok(buf)
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct EdgeConstraints {
    #[serde(default = "default_max_payload")]
    pub max_payload_bytes: u64,
    #[serde(default = "default_runtime_seconds")]
    pub max_runtime_seconds: u64,
    #[serde(default)]
    pub mqtt_subscribe: Vec<String>,
    #[serde(default)]
    pub mqtt_publish: Vec<String>,
}

fn default_max_payload() -> u64 {
    65536
}
fn default_runtime_seconds() -> u64 {
    30
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Manifest {
    pub name: String,
    pub slug: String,
    pub version: String,
    pub model: String,
    pub temperature: f64,
    pub max_iterations: u32,
    pub max_tokens: u32,
    pub tools: Vec<String>,
    pub edge_constraints: EdgeConstraints,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub tenant_id: Option<String>,
}

pub fn parse_manifest(yaml: &[u8]) -> Result<Manifest> {
    let m: Manifest = serde_yaml::from_slice(yaml).with_context(|| "failed to parse agent.yaml")?;
    validate_manifest(&m)?;
    Ok(m)
}

pub fn validate_manifest(m: &Manifest) -> Result<()> {
    if !valid_slug(&m.slug) {
        return Err(anyhow!(BundleError::new(format!(
            "manifest slug is not a safe name {}",
            m.slug
        ))));
    }
    for t in &m.tools {
        if !EDGE_SAFE_TOOLS.contains(t.as_str()) {
            return Err(anyhow!(BundleError::new(format!("tool not edge-safe {t}"))));
        }
    }
    Ok(())
}

// the received bytes with the signature.sig header and data blocks cut out
pub fn strip_signature(bundle: &[u8]) -> Vec<u8> {
    let mut off = 0usize;
    while off + 512 <= bundle.len() {
        let header = &bundle[off..off + 512];
        if header.iter().all(|b| *b == 0) {
            break;
        }
        let name_end = header[..100].iter().position(|b| *b == 0).unwrap_or(100);
        let name = String::from_utf8_lossy(&header[..name_end]);
        let size_txt: String = header[124..136]
            .iter()
            .map(|b| if *b == 0 { ' ' } else { *b as char })
            .collect();
        let size = usize::from_str_radix(size_txt.trim(), 8).unwrap_or(0);
        let end = off + 512 + size.div_ceil(512) * 512;
        if name == "signature.sig" {
            let mut out = bundle[..off].to_vec();
            if end < bundle.len() {
                out.extend_from_slice(&bundle[end..]);
            }
            return out;
        }
        off = end;
    }
    bundle.to_vec()
}

pub fn verify_signature(
    bundle: &[u8],
    pubkey: Option<&RsaPublicKey>,
    allow_unsigned: bool,
) -> Result<(Vec<u8>, Manifest)> {
    let (members, sig) = read_tar_members(bundle)?;
    let raw_tar = rebuild_tar(&members)?;
    match (&sig, pubkey) {
        (None, _) if !allow_unsigned => {
            return Err(anyhow!(BundleError::new(
                "bundle is unsigned, no signature.sig. Refusing to load, set EDGE_ALLOW_UNSIGNED=true only for local development"
            )));
        }
        (Some(_), None) if !allow_unsigned => {
            return Err(anyhow!(BundleError::new(
                "no signing public key configured, cannot verify bundle. Set SIGNING_PUBKEY_PEM or SIGNING_PUBKEY_PATH"
            )));
        }
        (Some(sig), Some(pk)) => {
            let verifying = VerifyingKey::<Sha256>::new(pk.clone());
            let signature = Signature::try_from(sig.as_slice())
                .map_err(|_| anyhow!(BundleError::new("bundle_signature_invalid")))?;
            // platform bundles sign the stripped bytes, older ones a rebuilt tar
            let stripped = strip_signature(bundle);
            verifying
                .verify(&stripped, &signature)
                .or_else(|_| verifying.verify(&raw_tar, &signature))
                .map_err(|_| anyhow!(BundleError::new("bundle_signature_invalid")))?;
        }
        _ => warn!("accepting UNVERIFIED bundle because EDGE_ALLOW_UNSIGNED=true, development only"),
    }
    let manifest_bytes = members
        .iter()
        .find(|(n, _, _, _)| n == "agent.yaml")
        .map(|(_, b, _, _)| b.clone())
        .ok_or_else(|| anyhow!(BundleError::new("bundle missing agent.yaml")))?;
    let manifest = parse_manifest(&manifest_bytes)?;
    Ok((raw_tar, manifest))
}

fn unique_suffix() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("{}-{nanos}", std::process::id())
}

// writes beside the live folder and swaps, so a failed install leaves the old agent serving
pub fn untar_to_dir(bundle: &[u8], dest: &Path) -> Result<()> {
    let (members, _) = read_tar_members(bundle)?;
    let name = dest
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_default();
    let parent = dest.parent().unwrap_or(Path::new("."));
    std::fs::create_dir_all(parent)?;
    let staging = parent.join(format!(".staging-{name}-{}", unique_suffix()));
    let write_all = || -> Result<()> {
        std::fs::create_dir_all(&staging)?;
        for (member, data, _, _) in &members {
            let target = staging.join(member);
            if member.ends_with('/') {
                std::fs::create_dir_all(&target)?;
                continue;
            }
            if let Some(p) = target.parent() {
                std::fs::create_dir_all(p)?;
            }
            std::fs::write(&target, data)?;
        }
        std::fs::write(staging.join(SAVED_BUNDLE), bundle)?;
        Ok(())
    };
    if let Err(e) = write_all() {
        let _ = std::fs::remove_dir_all(&staging);
        return Err(e);
    }
    let old = parent.join(format!(".old-{name}-{}", unique_suffix()));
    let had_old = dest.exists();
    if had_old {
        std::fs::rename(dest, &old)?;
    }
    if let Err(e) = std::fs::rename(&staging, dest) {
        if had_old {
            let _ = std::fs::rename(&old, dest);
        }
        let _ = std::fs::remove_dir_all(&staging);
        return Err(e.into());
    }
    if had_old {
        let _ = std::fs::remove_dir_all(&old);
    }
    Ok(())
}

#[derive(Clone)]
pub struct LoadedAgent {
    pub slug: String,
    pub dir: PathBuf,
    pub manifest: Manifest,
    pub digest: String,
    pub system_prompt: String,
}

impl LoadedAgent {
    pub fn to_json(&self) -> Value {
        json!({
            "slug": self.slug,
            "name": self.manifest.name,
            "version": self.manifest.version,
            "model": self.manifest.model,
            "tools": self.manifest.tools,
            "digest": self.digest,
            "edge_constraints": {
                "max_payload_bytes": self.manifest.edge_constraints.max_payload_bytes,
                "max_runtime_seconds": self.manifest.edge_constraints.max_runtime_seconds,
                "mqtt_subscribe": self.manifest.edge_constraints.mqtt_subscribe,
                "mqtt_publish": self.manifest.edge_constraints.mqtt_publish,
            }
        })
    }
}

pub struct Registry {
    pub cfg: Config,
    pub agents: RwLock<BTreeMap<String, LoadedAgent>>,
}

impl Registry {
    pub fn new(cfg: Config) -> Self {
        Self {
            cfg,
            agents: RwLock::new(BTreeMap::new()),
        }
    }

    pub async fn install_bundle(
        &self,
        bundle: &[u8],
        expected_slug: Option<&str>,
    ) -> Result<LoadedAgent> {
        let checked = (|| -> Result<Manifest> {
            let pubkey = load_pubkey(&self.cfg)?;
            let (_, manifest) =
                verify_signature(bundle, pubkey.as_ref(), self.cfg.allow_unsigned)?;
            self.check_tenant(&manifest)?;
            if let Some(want) = expected_slug {
                if want != manifest.slug {
                    return Err(anyhow!(BundleError::new(format!(
                        "bundle is for agent {}, it was sent to {want}",
                        manifest.slug
                    ))));
                }
            }
            Ok(manifest)
        })();
        let manifest = match checked {
            Ok(m) => m,
            Err(e) => {
                // nothing was touched, whatever is loaded keeps serving
                error!(reason = %e, "bundle_rejected");
                return Err(e);
            }
        };
        let slug = manifest.slug.clone();
        let digest = hex::encode(Sha256::digest(bundle));
        let mut agents = self.agents.write().await;
        if let Some(current) = agents.get(&slug) {
            if current.digest == digest {
                return Ok(current.clone());
            }
        }
        let dest = self.cfg.bundle_dir.join(&slug);
        untar_to_dir(bundle, &dest)?;
        let system_prompt = std::fs::read_to_string(dest.join("system_prompt.md"))
            .unwrap_or_default();
        let agent = LoadedAgent {
            slug: slug.clone(),
            dir: dest,
            manifest,
            digest: digest.clone(),
            system_prompt,
        };
        agents.insert(slug.clone(), agent.clone());
        info!(slug = %slug, digest = %digest, "agent_loaded");
        Ok(agent)
    }

    fn check_tenant(&self, manifest: &Manifest) -> Result<()> {
        if self.cfg.tenant_id.is_empty() {
            return Ok(());
        }
        let bundle_tenant = manifest.tenant_id.clone().unwrap_or_default();
        if bundle_tenant != self.cfg.tenant_id {
            error!(slug = %manifest.slug, bundle_tenant = %bundle_tenant, runtime_tenant = %self.cfg.tenant_id, "bundle_tenant_mismatch");
            return Err(anyhow!(BundleError::new(format!(
                "bundle tenant_id {} does not match runtime TENANT_ID {}",
                if bundle_tenant.is_empty() { "<none>" } else { &bundle_tenant },
                self.cfg.tenant_id
            ))));
        }
        Ok(())
    }

    pub async fn get(&self, slug: &str) -> Option<LoadedAgent> {
        self.agents.read().await.get(slug).cloned()
    }

    pub async fn list(&self) -> Vec<LoadedAgent> {
        self.agents.read().await.values().cloned().collect()
    }

    pub async fn count(&self) -> usize {
        self.agents.read().await.len()
    }

    pub async fn reload_from_disk(&self) {
        if !self.cfg.bundle_dir.exists() {
            return;
        }
        let entries = match std::fs::read_dir(&self.cfg.bundle_dir) {
            Ok(e) => e,
            Err(_) => return,
        };
        // the saved bundle goes through the full install, so a tampered volume stays out
        for entry in entries.flatten() {
            let dir = entry.path();
            let name = entry.file_name().to_string_lossy().into_owned();
            if name.starts_with('.') {
                let _ = std::fs::remove_dir_all(&dir);
                continue;
            }
            if !dir.is_dir() {
                continue;
            }
            let saved = match std::fs::read(dir.join(SAVED_BUNDLE)) {
                Ok(b) => b,
                Err(_) => {
                    warn!(dir = ?dir, "agent_reload_failed no saved bundle, push the agent again");
                    continue;
                }
            };
            match self.install_bundle(&saved, Some(&name)).await {
                Ok(a) => info!(slug = %a.slug, "agent_reloaded_from_disk"),
                Err(e) => warn!(dir = ?dir, err = %e, "agent_reload_failed"),
            }
        }
    }
}

// python3 with no shell, no inherited environment and its own process group
pub async fn run_code_executor(code: &str, timeout_secs: u64) -> Value {
    let scratch = std::env::temp_dir().join(format!("edge-code-{}", unique_suffix()));
    if let Err(e) = std::fs::create_dir_all(&scratch) {
        return json!({"ok": false, "error": format!("scratch_failed {e}")});
    }
    let mut cmd = tokio::process::Command::new("python3");
    cmd.arg("-I")
        .arg("-c")
        .arg(code)
        .env_clear()
        .env("PATH", "/usr/local/bin:/usr/bin:/bin")
        .env("HOME", &scratch)
        .current_dir(&scratch)
        .process_group(0)
        .kill_on_drop(true)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => {
            let _ = std::fs::remove_dir_all(&scratch);
            return json!({"ok": false, "error": format!("spawn_failed {e}")});
        }
    };
    let pid = child.id();
    let result = match tokio::time::timeout(
        Duration::from_secs(timeout_secs),
        child.wait_with_output(),
    )
    .await
    {
        Ok(Ok(out)) => {
            let cut = |b: &[u8]| {
                String::from_utf8_lossy(&b[..b.len().min(CODE_OUTPUT_BYTES)]).into_owned()
            };
            json!({
                "ok": out.status.success(),
                "stdout": cut(&out.stdout),
                "stderr": cut(&out.stderr),
                "exit_code": out.status.code().unwrap_or(-1),
            })
        }
        Ok(Err(e)) => json!({"ok": false, "error": format!("wait_failed {e}")}),
        Err(_) => {
            if let Some(pid) = pid {
                // the whole group, a forked child must not outlive the limit
                unsafe {
                    libc::killpg(pid as i32, libc::SIGKILL);
                }
            }
            json!({"ok": false, "error": "code_executor_timeout"})
        }
    };
    let _ = std::fs::remove_dir_all(&scratch);
    result
}

pub async fn call_anthropic(
    cfg: &Config,
    manifest: &Manifest,
    system_prompt: &str,
    user_message: &str,
    timeout_secs: u64,
) -> Value {
    if cfg.anthropic_api_key.is_empty() && cfg.anthropic_auth_token.is_empty() {
        return json!({
            "ok": false,
            "error": "ANTHROPIC_API_KEY not configured on edge runtime",
            "stub": true,
            "echo": user_message,
        });
    }
    let body = json!({
        "model": manifest.model,
        "max_tokens": manifest.max_tokens,
        "temperature": manifest.temperature,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    });
    let url = format!("{}/v1/messages", cfg.anthropic_base_url.trim_end_matches('/'));
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(timeout_secs))
        .build()
    {
        Ok(c) => c,
        Err(e) => return json!({"ok": false, "error": format!("client_build {e}")}),
    };
    let request = client.post(&url);
    let request = if cfg.anthropic_api_key.is_empty() {
        request
            .header("authorization", format!("Bearer {}", cfg.anthropic_auth_token))
            .header("anthropic-beta", OAUTH_BETA)
    } else {
        request.header("x-api-key", &cfg.anthropic_api_key)
    };
    match request
        .header("anthropic-version", "2023-06-01")
        .header("content-type", "application/json")
        .json(&body)
        .send()
        .await
    {
        Ok(r) => {
            if !r.status().is_success() {
                let status = r.status();
                let txt = r.text().await.unwrap_or_default();
                return json!({"ok": false, "error": format!("model call answered {} {}", status.as_u16(), txt.chars().take(300).collect::<String>())});
            }
            match r.json::<Value>().await {
                Ok(data) => {
                    let mut text = String::new();
                    if let Some(arr) = data.get("content").and_then(|v| v.as_array()) {
                        for block in arr {
                            if block.get("type").and_then(|v| v.as_str()) == Some("text") {
                                if let Some(t) = block.get("text").and_then(|v| v.as_str()) {
                                    text.push_str(t);
                                }
                            }
                        }
                    }
                    json!({"ok": true, "text": text, "usage": data.get("usage").cloned().unwrap_or(json!({}))})
                }
                Err(e) => json!({"ok": false, "error": format!("decode {e}")}),
            }
        }
        Err(e) => json!({"ok": false, "error": format!("model call failed {e}")}),
    }
}

pub async fn execute_agent(
    cfg: &Config,
    agent: &LoadedAgent,
    user_message: &str,
    params: &Value,
) -> Value {
    let max_payload = agent.manifest.edge_constraints.max_payload_bytes;
    if user_message.len() as u64 > max_payload {
        return json!({"ok": false, "error": format!("payload exceeds {max_payload} bytes")});
    }
    let weights = agent.dir.join("model_weights");
    if weights.exists() {
        if let Ok(mut rd) = std::fs::read_dir(&weights) {
            if rd.next().is_some() {
                return json!({
                    "ok": false,
                    "error": "local model_weights present but no local inference shipped in v1.1",
                    "phase_2": true,
                });
            }
        }
    }
    let max_runtime = match agent.manifest.edge_constraints.max_runtime_seconds {
        0 => default_runtime_seconds(),
        n => n,
    };
    let started = std::time::Instant::now();
    // same contract as the other runtimes, params.code needs the gateway flag and the tool
    let code = params.get("code").and_then(|v| v.as_str()).unwrap_or("");
    let work = async {
        if code.is_empty() {
            call_anthropic(
                cfg,
                &agent.manifest,
                &agent.system_prompt,
                user_message,
                max_runtime,
            )
            .await
        } else if !cfg.code_enabled {
            json!({"ok": false, "error": "code_executor is off on this gateway, set EDGE_ENABLE_CODE_EXECUTOR=true to allow it"})
        } else if !agent.manifest.tools.iter().any(|t| t == "code_executor") {
            json!({"ok": false, "error": "code_executor not in tool whitelist"})
        } else {
            run_code_executor(code, CODE_TIMEOUT_SECONDS.min(max_runtime)).await
        }
    };
    let result = match tokio::time::timeout(Duration::from_secs(max_runtime), work).await {
        Ok(r) => r,
        Err(_) => json!({
            "ok": false,
            "error": format!("max_runtime_seconds exceeded after {max_runtime} s"),
            "error_code": "max_runtime_exceeded",
        }),
    };
    let duration_ms = started.elapsed().as_millis() as u64;
    json!({
        "slug": agent.slug,
        "digest": agent.digest,
        "duration_ms": duration_ms,
        "params": params,
        "result": result,
    })
}

#[derive(Clone)]
pub struct AppState {
    pub cfg: Arc<Config>,
    pub registry: Arc<Registry>,
}

fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    a.len() == b.len() && a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

pub fn authorized(cfg: &Config, headers: &HeaderMap) -> bool {
    if cfg.allow_no_auth {
        return true;
    }
    if cfg.auth_token.is_empty() {
        return false;
    }
    let value = headers
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    match value.trim().split_once(' ') {
        Some((scheme, token)) if scheme.eq_ignore_ascii_case("bearer") => {
            constant_time_eq(token.trim().as_bytes(), cfg.auth_token.as_bytes())
        }
        _ => false,
    }
}

async fn require_token(State(state): State<AppState>, req: Request, next: Next) -> Response {
    if authorized(&state.cfg, req.headers()) {
        return next.run(req).await;
    }
    (
        StatusCode::UNAUTHORIZED,
        [(header::WWW_AUTHENTICATE, "Bearer")],
        Json(json!({
            "error": "unauthorized",
            "message": "Send Authorization: Bearer with this gateway's EDGE_AUTH_TOKEN",
        })),
    )
        .into_response()
}

pub async fn health(State(state): State<AppState>) -> impl IntoResponse {
    let agents = state.registry.count().await;
    Json(json!({
        "status": "ok",
        "agents": agents,
        "gateway_id": state.cfg.gateway_id,
    }))
}

pub async fn list_agents(State(state): State<AppState>) -> impl IntoResponse {
    let agents: Vec<Value> = state
        .registry
        .list()
        .await
        .iter()
        .map(|a| a.to_json())
        .collect();
    Json(json!({"agents": agents}))
}

pub async fn install_bundle_handler(
    AxPath(slug): AxPath<String>,
    State(state): State<AppState>,
    body: Bytes,
) -> impl IntoResponse {
    if !valid_slug(&slug) {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({"error": "unsafe agent slug"})),
        )
            .into_response();
    }
    match state.registry.install_bundle(&body, Some(&slug)).await {
        Ok(a) => (StatusCode::OK, Json(json!({"loaded": a.to_json()}))).into_response(),
        Err(e) => (
            StatusCode::BAD_REQUEST,
            Json(json!({"error": e.to_string(), "slug": slug})),
        )
            .into_response(),
    }
}

pub async fn execute_handler(
    AxPath(slug): AxPath<String>,
    State(state): State<AppState>,
    body: Bytes,
) -> impl IntoResponse {
    let agent = match state.registry.get(&slug).await {
        Some(a) => a,
        None => {
            return (
                StatusCode::NOT_FOUND,
                Json(json!({"error": format!("unknown agent {slug}")})),
            )
                .into_response()
        }
    };
    let payload: Value = if body.is_empty() {
        json!({})
    } else {
        match serde_json::from_slice(&body) {
            Ok(v) => v,
            Err(_) => {
                return (
                    StatusCode::BAD_REQUEST,
                    Json(json!({"error": "body is not valid JSON"})),
                )
                    .into_response()
            }
        }
    };
    let user_message = payload
        .get("message")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let params = payload.get("params").cloned().unwrap_or(json!({}));
    let result = execute_agent(&state.cfg, &agent, &user_message, &params).await;
    (StatusCode::OK, Json(result)).into_response()
}

pub fn build_router(state: AppState) -> Router {
    let protected = Router::new()
        .route("/agents/:slug/bundle", post(install_bundle_handler))
        .route("/agents/:slug/execute", post(execute_handler))
        .route_layer(middleware::from_fn_with_state(state.clone(), require_token));
    Router::new()
        .route("/health", get(health))
        .route("/agents", get(list_agents))
        .merge(protected)
        .layer(DefaultBodyLimit::max(MAX_BUNDLE_BYTES))
        .with_state(state)
}

pub async fn run_http(state: AppState, port: u16) -> Result<()> {
    let app = build_router(state);
    let addr = format!("0.0.0.0:{port}");
    let listener = tokio::net::TcpListener::bind(&addr).await?;
    info!(port, "http_listening");
    axum::serve(listener, app).await?;
    Ok(())
}

pub async fn register_with_platform(cfg: &Config) -> bool {
    if cfg.platform_url.is_empty() || cfg.platform_token.is_empty() {
        warn!(
            platform_url = !cfg.platform_url.is_empty(),
            platform_token = !cfg.platform_token.is_empty(),
            "skip_register"
        );
        return false;
    }
    let url = format!(
        "{}/api/edge/gateways/register",
        cfg.platform_url.trim_end_matches('/')
    );
    let body = json!({
        "gateway_id": cfg.gateway_id,
        "name": cfg.gateway_name,
        "endpoint_url": cfg.endpoint_url,
    });
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(8))
        .build()
    {
        Ok(c) => c,
        Err(_) => return false,
    };
    match client
        .post(&url)
        .header("Authorization", format!("Bearer {}", cfg.platform_token))
        .json(&body)
        .send()
        .await
    {
        Ok(r) => {
            let s = r.status();
            if s.is_success() {
                info!(status = s.as_u16(), "registered_with_platform");
                true
            } else {
                warn!(status = s.as_u16(), "register_failed");
                false
            }
        }
        Err(e) => {
            warn!(err = %e, "register_failed");
            false
        }
    }
}

pub async fn register_loop(cfg: Arc<Config>) {
    loop {
        let _ = register_with_platform(&cfg).await;
        tokio::time::sleep(Duration::from_secs(60)).await;
    }
}

// a bundle is a tar padded to 10240 bytes, past rumqttc's 10 KiB default, so every OTA push was dropped
pub const MQTT_MAX_PACKET_BYTES: usize = 8 * 1024 * 1024;

pub fn mqtt_options(gateway_id: &str, host: String, port: u16) -> MqttOptions {
    let mut opts = MqttOptions::new(format!("edge-{gateway_id}"), host, port);
    opts.set_keep_alive(Duration::from_secs(30));
    opts.set_max_packet_size(MQTT_MAX_PACKET_BYTES, MQTT_MAX_PACKET_BYTES);
    opts
}

// mqtt://user:pass@host:port, anything missing falls back to no login and 1883
pub fn parse_mqtt_url(url: &str) -> (String, u16, Option<(String, String)>) {
    let rest = url.split("://").last().unwrap_or(url);
    let rest = rest.split('/').next().unwrap_or(rest);
    let (login, hostport) = match rest.rsplit_once('@') {
        Some((l, h)) => (Some(l), h),
        None => (None, rest),
    };
    let (host, port) = match hostport.split_once(':') {
        Some((h, p)) => (h, p.parse().unwrap_or(1883)),
        None => (hostport, 1883),
    };
    let creds = login.map(|l| match l.split_once(':') {
        Some((u, p)) => (u.to_string(), p.to_string()),
        None => (l.to_string(), String::new()),
    });
    let host = if host.is_empty() { "localhost" } else { host };
    (host.to_string(), port, creds)
}

pub async fn mqtt_loop(cfg: Arc<Config>, registry: Arc<Registry>) {
    if cfg.mqtt_url.is_empty() {
        info!("mqtt_disabled");
        return;
    }
    let (host, port, creds) = parse_mqtt_url(&cfg.mqtt_url);
    let topic = deploy_topic(&cfg.gateway_id, "+");
    let prefix = deploy_topic(&cfg.gateway_id, "");
    let mut opts = mqtt_options(&cfg.gateway_id, host, port);
    if let Some((user, pass)) = creds {
        opts.set_credentials(user, pass);
    }
    let (client, mut eventloop) = AsyncClient::new(opts, 16);
    loop {
        match eventloop.poll().await {
            // every connect subscribes again, retained bundles arrive right after
            Ok(Event::Incoming(Incoming::ConnAck(_))) => {
                match client.try_subscribe(&topic, QoS::AtLeastOnce) {
                    Ok(_) => info!(%topic, "mqtt_subscribed"),
                    Err(e) => warn!(err = %e, "mqtt_subscribe_failed"),
                }
            }
            Ok(Event::Incoming(Incoming::Publish(p))) => {
                // clearing a retained bundle arrives as an empty message
                let Some(slug) = p.topic.strip_prefix(&prefix) else {
                    continue;
                };
                if p.payload.is_empty() {
                    continue;
                }
                let digest = hex::encode(Sha256::digest(&p.payload));
                let ack = match registry.install_bundle(&p.payload, Some(slug)).await {
                    Ok(a) => {
                        info!(slug = %a.slug, "mqtt_bundle_loaded");
                        json!({"slug": slug, "digest": digest, "ok": true})
                    }
                    Err(e) => {
                        error!(slug = %slug, err = %e, "mqtt_bundle_failed");
                        json!({"slug": slug, "digest": digest, "ok": false, "error": e.to_string()})
                    }
                };
                let _ = client.try_publish(
                    ack_topic(&cfg.gateway_id, slug),
                    QoS::AtLeastOnce,
                    false,
                    ack.to_string(),
                );
            }
            Ok(_) => {}
            Err(e) => {
                error!(err = %e, "mqtt_loop_failed");
                tokio::time::sleep(Duration::from_secs(5)).await;
            }
        }
    }
}
