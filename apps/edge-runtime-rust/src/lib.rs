// AgentForge edge runtime — Rust port of apps/edge-runtime/runtime.py.
// Single static binary that serves :8080, subscribes to MQTT for OTA bundles,
// verifies RSA-PSS signatures, extracts agent bundles, and proxies execute
// calls to Anthropic.

use std::collections::{BTreeMap, HashSet};
use std::io::{Cursor, Read};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use axum::{
    extract::{Path as AxPath, State},
    http::StatusCode,
    response::IntoResponse,
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
use tokio::io::AsyncWriteExt;
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
    pub anthropic_base_url: String,
    pub port: u16,
}

impl Config {
    // explicit constructor for tests — sidesteps process-global env vars.
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
            anthropic_base_url: "https://api.anthropic.com".into(),
            port: 0,
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
            anthropic_api_key: std::env::var("ANTHROPIC_API_KEY").unwrap_or_default(),
            anthropic_base_url: std::env::var("ANTHROPIC_BASE_URL")
                .unwrap_or_else(|_| "https://api.anthropic.com".into()),
            port: std::env::var("PORT")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(8080),
        }
    }
}

// ─── bundle handling ──────────────────────────────────────────────────────

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

pub fn read_tar_members(
    bundle: &[u8],
) -> Result<(Vec<(String, Vec<u8>, u64, u32)>, Option<Vec<u8>>)> {
    let mut archive = tar::Archive::new(Cursor::new(bundle));
    let mut members: Vec<(String, Vec<u8>, u64, u32)> = Vec::new();
    let mut sig: Option<Vec<u8>> = None;
    for entry in archive.entries()? {
        let mut e = entry?;
        let path = e.path()?.to_string_lossy().into_owned();
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
}

pub fn parse_manifest(yaml: &[u8]) -> Result<Manifest> {
    let m: Manifest = serde_yaml::from_slice(yaml).with_context(|| "failed to parse agent.yaml")?;
    validate_manifest(&m)?;
    Ok(m)
}

pub fn validate_manifest(m: &Manifest) -> Result<()> {
    for t in &m.tools {
        if t.starts_with("atlas_") || t.starts_with("mcp_") {
            return Err(anyhow!(BundleError::new(format!("tool not edge-safe: {t}"))));
        }
        if !EDGE_SAFE_TOOLS.contains(t.as_str()) {
            return Err(anyhow!(BundleError::new(format!("tool not edge-safe: {t}"))));
        }
    }
    Ok(())
}

pub fn verify_signature(bundle: &[u8], pubkey: Option<&RsaPublicKey>) -> Result<(Vec<u8>, Manifest)> {
    let (members, sig) = read_tar_members(bundle)?;
    let sig = sig.ok_or_else(|| anyhow!(BundleError::new("bundle missing signature.sig")))?;
    let raw_tar = rebuild_tar(&members)?;
    if let Some(pk) = pubkey {
        let verifying = VerifyingKey::<Sha256>::new(pk.clone());
        let signature = Signature::try_from(sig.as_slice())
            .map_err(|e| anyhow!(BundleError::new(format!("bundle_signature_invalid: {e}"))))?;
        verifying
            .verify(&raw_tar, &signature)
            .map_err(|e| anyhow!(BundleError::new(format!("bundle_signature_invalid: {e}"))))?;
    } else {
        warn!("no signing pubkey configured — accepting bundle UNVERIFIED");
    }
    let manifest_bytes = members
        .iter()
        .find(|(n, _, _, _)| n == "agent.yaml")
        .map(|(_, b, _, _)| b.clone())
        .ok_or_else(|| anyhow!(BundleError::new("bundle missing agent.yaml")))?;
    let manifest = parse_manifest(&manifest_bytes)?;
    Ok((raw_tar, manifest))
}

pub fn untar_to_dir(bundle: &[u8], dest: &Path) -> Result<()> {
    if dest.exists() {
        std::fs::remove_dir_all(dest)?;
    }
    std::fs::create_dir_all(dest)?;
    let mut archive = tar::Archive::new(Cursor::new(bundle));
    for entry in archive.entries()? {
        let mut e = entry?;
        let path = e.path()?.to_string_lossy().into_owned();
        if path.contains("..") || path.starts_with('/') {
            return Err(anyhow!(BundleError::new(format!("unsafe path in bundle: {path}"))));
        }
        e.unpack_in(dest)?;
    }
    Ok(())
}

// ─── registry + executor ──────────────────────────────────────────────────

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

    pub async fn install_bundle(&self, bundle: &[u8]) -> Result<LoadedAgent> {
        let pubkey = load_pubkey(&self.cfg)?;
        let (_, manifest) = verify_signature(bundle, pubkey.as_ref())?;
        let slug = manifest.slug.clone();
        let dest = self.cfg.bundle_dir.join(&slug);
        untar_to_dir(bundle, &dest)?;
        let digest = hex::encode(Sha256::digest(bundle));
        let system_prompt = std::fs::read_to_string(dest.join("system_prompt.md"))
            .unwrap_or_default();
        let agent = LoadedAgent {
            slug: slug.clone(),
            dir: dest,
            manifest,
            digest: digest.clone(),
            system_prompt,
        };
        self.agents.write().await.insert(slug.clone(), agent.clone());
        info!(slug = %slug, digest = %digest, "agent_loaded");
        Ok(agent)
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
        for entry in entries.flatten() {
            let dir = entry.path();
            if !dir.is_dir() {
                continue;
            }
            let mp = dir.join("agent.yaml");
            if !mp.exists() {
                continue;
            }
            match (|| -> Result<LoadedAgent> {
                let bytes = std::fs::read(&mp)?;
                let manifest = parse_manifest(&bytes)?;
                let slug = manifest.slug.clone();
                let fake_digest = hex::encode(Sha256::digest(slug.as_bytes()));
                let system_prompt = std::fs::read_to_string(dir.join("system_prompt.md"))
                    .unwrap_or_default();
                Ok(LoadedAgent {
                    slug,
                    dir: dir.clone(),
                    manifest,
                    digest: fake_digest,
                    system_prompt,
                })
            })() {
                Ok(a) => {
                    info!(slug = %a.slug, "agent_reloaded_from_disk");
                    self.agents.write().await.insert(a.slug.clone(), a);
                }
                Err(e) => warn!(dir = ?dir, err = %e, "agent_reload_failed"),
            }
        }
    }
}

// ─── code_executor subprocess ─────────────────────────────────────────────

pub async fn run_code_executor(code: &str) -> Value {
    let mut cmd = tokio::process::Command::new("python3");
    cmd.arg("-c")
        .arg(code)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => return json!({"ok": false, "error": format!("spawn_failed: {e}")}),
    };
    if let Some(mut stdin) = child.stdin.take() {
        let _ = stdin.shutdown().await;
    }
    let fut = child.wait_with_output();
    match tokio::time::timeout(Duration::from_secs(5), fut).await {
        Ok(Ok(out)) => json!({
            "ok": out.status.success(),
            "stdout": String::from_utf8_lossy(&out.stdout),
            "stderr": String::from_utf8_lossy(&out.stderr),
            "exit_code": out.status.code().unwrap_or(-1),
        }),
        Ok(Err(e)) => json!({"ok": false, "error": format!("wait_failed: {e}")}),
        Err(_) => json!({"ok": false, "error": "code_executor_timeout"}),
    }
}

// ─── anthropic call ───────────────────────────────────────────────────────

pub async fn call_anthropic(
    cfg: &Config,
    manifest: &Manifest,
    system_prompt: &str,
    user_message: &str,
) -> Value {
    if cfg.anthropic_api_key.is_empty() {
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
        .timeout(Duration::from_secs(30))
        .build()
    {
        Ok(c) => c,
        Err(e) => return json!({"ok": false, "error": format!("client_build: {e}")}),
    };
    match client
        .post(&url)
        .header("x-api-key", &cfg.anthropic_api_key)
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
                return json!({"ok": false, "error": format!("http {}: {}", status, txt)});
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
                Err(e) => json!({"ok": false, "error": format!("decode: {e}")}),
            }
        }
        Err(e) => json!({"ok": false, "error": e.to_string()}),
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
    let started = std::time::Instant::now();
    let result = call_anthropic(cfg, &agent.manifest, &agent.system_prompt, user_message).await;
    let duration_ms = started.elapsed().as_millis() as u64;
    json!({
        "slug": agent.slug,
        "digest": agent.digest,
        "duration_ms": duration_ms,
        "params": params,
        "result": result,
    })
}

// ─── HTTP layer ───────────────────────────────────────────────────────────

#[derive(Clone)]
pub struct AppState {
    pub cfg: Arc<Config>,
    pub registry: Arc<Registry>,
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
    match state.registry.install_bundle(&body).await {
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
        serde_json::from_slice(&body).unwrap_or(json!({}))
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
    Router::new()
        .route("/health", get(health))
        .route("/agents", get(list_agents))
        .route("/agents/:slug/bundle", post(install_bundle_handler))
        .route("/agents/:slug/execute", post(execute_handler))
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

// ─── platform registration ────────────────────────────────────────────────

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

// ─── MQTT subscriber ──────────────────────────────────────────────────────

pub async fn mqtt_loop(cfg: Arc<Config>, registry: Arc<Registry>) {
    if cfg.mqtt_url.is_empty() {
        info!("mqtt_disabled");
        return;
    }
    let stripped = cfg.mqtt_url.replace("mqtt://", "");
    let mut parts = stripped.split(':');
    let host = parts.next().unwrap_or("localhost").to_string();
    let port: u16 = parts
        .next()
        .and_then(|p| p.split('/').next())
        .and_then(|p| p.parse().ok())
        .unwrap_or(1883);
    let topic = format!("edge.{}.deploy", cfg.gateway_id);
    let mut opts = MqttOptions::new(format!("edge-{}", cfg.gateway_id), host, port);
    opts.set_keep_alive(Duration::from_secs(30));
    let (client, mut eventloop) = AsyncClient::new(opts, 16);
    if let Err(e) = client.subscribe(&topic, QoS::AtLeastOnce).await {
        warn!(err = %e, "mqtt_subscribe_failed");
        return;
    }
    info!(%topic, "mqtt_subscribed");
    loop {
        match eventloop.poll().await {
            Ok(Event::Incoming(Incoming::Publish(p))) => {
                if p.topic == topic {
                    match registry.install_bundle(&p.payload).await {
                        Ok(a) => info!(slug = %a.slug, "mqtt_bundle_loaded"),
                        Err(e) => error!(err = %e, "mqtt_bundle_failed"),
                    }
                }
            }
            Ok(_) => {}
            Err(e) => {
                error!(err = %e, "mqtt_loop_failed");
                tokio::time::sleep(Duration::from_secs(5)).await;
            }
        }
    }
}
