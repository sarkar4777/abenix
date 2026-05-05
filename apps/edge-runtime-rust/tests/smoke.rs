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

