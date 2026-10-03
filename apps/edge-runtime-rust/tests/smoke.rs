use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use edge_runtime_rust::{rebuild_tar, AppState, Config, Registry};
use rsa::pkcs8::EncodePublicKey;
use rsa::pss::SigningKey;
use rsa::signature::{RandomizedSigner, SignatureEncoding};
use rsa::{RsaPrivateKey, RsaPublicKey};
use serde_json::Value;
use sha2::Sha256;
use tempfile::TempDir;

fn build_signed_bundle(slug: &str, key: &RsaPrivateKey) -> Vec<u8> {
    let manifest_yaml = format!(
        "name: Smoke Agent\n\
slug: {slug}\n\
version: 0.1.0\n\
model: claude-sonnet-4-5-20250929\n\
temperature: 0.2\n\
max_iterations: 3\n\
max_tokens: 256\n\
tools:\n  - current_time\n  - mqtt_publish\n\
edge_constraints:\n  max_payload_bytes: 4096\n  max_runtime_seconds: 5\n  mqtt_subscribe: []\n  mqtt_publish:\n    - alerts.smoke\n",
    );
    let mtime = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs();

    let members: Vec<(String, Vec<u8>, u64, u32)> = vec![
        (
            "agent.yaml".to_string(),
            manifest_yaml.into_bytes(),
            mtime,
            0o644,
        ),
        (
            "system_prompt.md".to_string(),
            b"You are a smoke-test agent.".to_vec(),
            mtime,
            0o644,
        ),
    ];

    // raw tar (members only) — what the signature is computed over.
    let raw_tar = rebuild_tar(&members).unwrap();

    let signing_key = SigningKey::<Sha256>::new(key.clone());
    let mut rng = rand::thread_rng();
    let sig = signing_key.sign_with_rng(&mut rng, &raw_tar);
    let sig_bytes = sig.to_bytes().to_vec();

    let mut full_members = members.clone();
    full_members.push(("signature.sig".to_string(), sig_bytes, mtime, 0o644));

    // build the on-the-wire bundle with signature.sig appended as the last entry.
    let mut out = Vec::new();
    {
        let mut builder = tar::Builder::new(&mut out);
        for (name, data, mt, mode) in &full_members {
            let mut header = tar::Header::new_ustar();
            header.set_size(data.len() as u64);
            header.set_mtime(*mt);
            header.set_mode(*mode);
            header.set_entry_type(tar::EntryType::Regular);
            header.set_cksum();
            builder.append_data(&mut header, name, &data[..]).unwrap();
        }
        builder.finish().unwrap();
    }
    out
}

async fn boot(port: u16, tmp: &TempDir, pub_pem_path: PathBuf) -> AppState {
    let cfg = Arc::new(Config::for_test(
        tmp.path().join("agents"),
        pub_pem_path,
        format!("smoke-{port}"),
    ));
    let registry = Arc::new(Registry::new((*cfg).clone()));
    let state = AppState {
        cfg: cfg.clone(),
        registry: registry.clone(),
    };
    let st = state.clone();
    tokio::spawn(async move {
        let _ = edge_runtime_rust::run_http(st, port).await;
    });
    // give axum a moment to bind.
    tokio::time::sleep(Duration::from_millis(400)).await;
    state
}

#[tokio::test]
async fn boots_loads_executes() {
    let tmp = TempDir::new().unwrap();
    let mut rng = rand::thread_rng();
    let key = RsaPrivateKey::new(&mut rng, 2048).unwrap();
    let pub_pem = RsaPublicKey::from(&key)
        .to_public_key_pem(rsa::pkcs8::LineEnding::LF)
        .unwrap();
    let pub_path = tmp.path().join("pub.pem");
    std::fs::write(&pub_path, pub_pem).unwrap();

    let port = 18088u16;
    let _state = boot(port, &tmp, pub_path).await;

    let bundle = build_signed_bundle("smoke-agent", &key);

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .unwrap();
    let base = format!("http://127.0.0.1:{port}");

    let r = client.get(format!("{base}/health")).send().await.unwrap();
    assert_eq!(r.status(), 200);
    let v: Value = r.json().await.unwrap();
    assert_eq!(v["agents"], 0);

    let r = client
        .post(format!("{base}/agents/smoke-agent/bundle"))
        .header("Content-Type", "application/x-tar")
        .body(bundle)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200, "bundle install failed: {:?}", r.text().await);

    let r = client.get(format!("{base}/agents")).send().await.unwrap();
    assert_eq!(r.status(), 200);
    let v: Value = r.json().await.unwrap();
    let arr = v["agents"].as_array().unwrap();
    assert!(arr.iter().any(|a| a["slug"] == "smoke-agent"));

    let r = client
        .post(format!("{base}/agents/smoke-agent/execute"))
        .json(&serde_json::json!({"message": "hi"}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    let v: Value = r.json().await.unwrap();
    assert_eq!(v["slug"], "smoke-agent");
    assert!(v.get("result").is_some());
    assert!(v["duration_ms"].is_number());
    // no anthropic key in test env, runtime echoes the message.
    assert_eq!(v["result"]["echo"], "hi");
}

#[tokio::test]
async fn invalid_signature_rejected() {
    let tmp = TempDir::new().unwrap();
    let mut rng = rand::thread_rng();
    let key = RsaPrivateKey::new(&mut rng, 2048).unwrap();
    let other = RsaPrivateKey::new(&mut rng, 2048).unwrap();

    let bundle = build_signed_bundle("bad-agent", &key);

    let pub_pem = RsaPublicKey::from(&other)
        .to_public_key_pem(rsa::pkcs8::LineEnding::LF)
        .unwrap();
    let pub_path = tmp.path().join("pub.pem");
    std::fs::write(&pub_path, pub_pem).unwrap();

    let cfg = Config::for_test(tmp.path().join("a2"), pub_path, "bad".into());
    let registry = Registry::new(cfg);
    let res = registry.install_bundle(&bundle).await;
    assert!(res.is_err(), "expected install_bundle to reject mismatched signature");
    let msg = format!("{:?}", res.err().unwrap());
    assert!(
        msg.contains("bundle_signature_invalid") || msg.contains("signature"),
        "unexpected error: {msg}"
    );
}


// laid out like the platform compiler: placeholder signature entry, record padding,
// then the signature computed over the bytes with that entry cut out
fn build_platform_bundle(slug: &str, tools: &[&str], key: &RsaPrivateKey) -> Vec<u8> {
    let tool_lines: String = tools.iter().map(|t| format!("  - {t}\n")).collect();
    let manifest_yaml = format!(
        "name: Platform Agent\nslug: {slug}\nversion: 0.1.0\nmodel: claude-haiku-4-5\n\
temperature: 0.1\nmax_iterations: 2\nmax_tokens: 256\ntools:\n{tool_lines}\
edge_constraints:\n  max_payload_bytes: 4096\n  max_runtime_seconds: 5\n",
    );
    let members: Vec<(String, Vec<u8>)> = vec![
        ("agent.yaml".into(), manifest_yaml.into_bytes()),
        ("system_prompt.md".into(), b"edge agent".to_vec()),
        ("signature.sig".into(), vec![0u8; 256]),
    ];
    let mut out = Vec::new();
    {
        let mut builder = tar::Builder::new(&mut out);
        for (name, data) in &members {
            let mut header = tar::Header::new_ustar();
            header.set_size(data.len() as u64);
            header.set_mtime(1_700_000_000);
            header.set_mode(0o644);
            header.set_entry_type(tar::EntryType::Regular);
            header.set_cksum();
            builder.append_data(&mut header, name, &data[..]).unwrap();
        }
        builder.finish().unwrap();
    }
    // python tarfile pads to a 10240 byte record
    let padded = out.len().div_ceil(10240) * 10240;
    out.resize(padded, 0);

    let stripped = edge_runtime_rust::strip_signature(&out);
    assert_eq!(stripped.len(), out.len() - 1024);
    let signing_key = SigningKey::<Sha256>::new(key.clone());
    let sig = signing_key
        .sign_with_rng(&mut rand::thread_rng(), &stripped)
        .to_bytes()
        .to_vec();
    // signature.sig is the third entry, its data starts after two 1024 byte members and its header
    let data_start = 1024 * 2 + 512;
    out[data_start..data_start + 256].copy_from_slice(&sig);
    out
}

fn key_and_pub(tmp: &TempDir) -> (RsaPrivateKey, PathBuf) {
    let key = RsaPrivateKey::new(&mut rand::thread_rng(), 2048).unwrap();
    let pub_pem = RsaPublicKey::from(&key)
        .to_public_key_pem(rsa::pkcs8::LineEnding::LF)
        .unwrap();
    let pub_path = tmp.path().join("pub.pem");
    std::fs::write(&pub_path, pub_pem).unwrap();
    (key, pub_path)
}

#[tokio::test]
async fn platform_signed_bundle_loads() {
    let tmp = TempDir::new().unwrap();
    let (key, pub_path) = key_and_pub(&tmp);
    let bundle = build_platform_bundle("platform-agent", &["current_time"], &key);
    let registry = Registry::new(Config::for_test(tmp.path().join("p"), pub_path, "p".into()));
    let loaded = registry.install_bundle(&bundle).await;
    assert!(loaded.is_ok(), "platform bundle rejected: {:?}", loaded.err());

    let mut tampered = bundle.clone();
    tampered[600] ^= 0x01;
    assert!(registry.install_bundle(&tampered).await.is_err());
}

#[tokio::test]
async fn params_code_runs_only_when_code_executor_allowed() {
    if std::process::Command::new("python3").arg("-c").arg("pass").status().is_err() {
        eprintln!("python3 not on PATH, skipping");
        return;
    }
    let tmp = TempDir::new().unwrap();
    let (key, pub_path) = key_and_pub(&tmp);
    let cfg = Config::for_test(tmp.path().join("c"), pub_path, "c".into());
    let registry = Registry::new(cfg.clone());

    let allowed = registry
        .install_bundle(&build_platform_bundle("coder", &["code_executor"], &key))
        .await
        .unwrap();
    let v = edge_runtime_rust::execute_agent(&cfg, &allowed, "", &serde_json::json!({"code": "print(6*7)"})).await;
    assert_eq!(v["result"]["ok"], true, "{v}");
    assert_eq!(v["result"]["stdout"].as_str().unwrap().trim(), "42");

    let denied = registry
        .install_bundle(&build_platform_bundle("no-coder", &["current_time"], &key))
        .await
        .unwrap();
    let v = edge_runtime_rust::execute_agent(&cfg, &denied, "", &serde_json::json!({"code": "print(1)"})).await;
    assert_eq!(v["result"]["ok"], false);
    assert!(v["result"]["error"].as_str().unwrap().contains("code_executor"));
}

#[test]
fn mqtt_accepts_a_full_bundle() {
    let opts = edge_runtime_rust::mqtt_options("gw", "localhost".into(), 1883);
    // the smallest platform bundle is one 10240 byte tar record plus the publish header
    assert!(opts.max_packet_size() > 10240 + 512);
}
