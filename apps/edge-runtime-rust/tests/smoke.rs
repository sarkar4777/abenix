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
        .body(bundle.clone())
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401, "bundle install needs the token");

    let r = client
        .post(format!("{base}/agents/smoke-agent/bundle"))
        .header("Content-Type", "application/x-tar")
        .bearer_auth("test-token")
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
    assert_eq!(r.status(), 401, "execute needs the token");

    let r = client
        .post(format!("{base}/agents/smoke-agent/execute"))
        .bearer_auth("test-token")
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
    let res = registry.install_bundle(&bundle, None).await;
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
    let loaded = registry.install_bundle(&bundle, None).await;
    assert!(loaded.is_ok(), "platform bundle rejected: {:?}", loaded.err());

    let mut tampered = bundle.clone();
    tampered[600] ^= 0x01;
    assert!(registry.install_bundle(&tampered, None).await.is_err());
}

#[tokio::test]
async fn params_code_runs_only_when_code_executor_allowed() {
    if std::process::Command::new("python3").arg("-c").arg("pass").status().is_err() {
        eprintln!("python3 not on PATH, skipping");
        return;
    }
    let tmp = TempDir::new().unwrap();
    let (key, pub_path) = key_and_pub(&tmp);
    let mut cfg = Config::for_test(tmp.path().join("c"), pub_path, "c".into());
    cfg.code_enabled = true;
    let registry = Registry::new(cfg.clone());

    let allowed = registry
        .install_bundle(&build_platform_bundle("coder", &["code_executor"], &key), None)
        .await
        .unwrap();
    let v = edge_runtime_rust::execute_agent(&cfg, &allowed, "", &serde_json::json!({"code": "print(6*7)"})).await;
    assert_eq!(v["result"]["ok"], true, "{v}");
    assert_eq!(v["result"]["stdout"].as_str().unwrap().trim(), "42");

    let denied = registry
        .install_bundle(&build_platform_bundle("no-coder", &["current_time"], &key), None)
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

#[tokio::test]
async fn params_code_is_off_by_default() {
    let tmp = TempDir::new().unwrap();
    let (key, pub_path) = key_and_pub(&tmp);
    let cfg = Config::for_test(tmp.path().join("off"), pub_path, "off".into());
    let registry = Registry::new(cfg.clone());
    let agent = registry
        .install_bundle(&build_platform_bundle("coder", &["code_executor"], &key), None)
        .await
        .unwrap();
    let v = edge_runtime_rust::execute_agent(&cfg, &agent, "", &serde_json::json!({"code": "print(1)"})).await;
    assert_eq!(v["result"]["ok"], false);
    assert!(v["result"]["error"].as_str().unwrap().contains("off"));
}

#[tokio::test]
async fn params_code_gets_a_scrubbed_environment_and_a_time_limit() {
    if std::process::Command::new("python3").arg("-c").arg("pass").status().is_err() {
        eprintln!("python3 not on PATH, skipping");
        return;
    }
    std::env::set_var("ABENIX_TEST_SECRET", "leak-me");
    let v = edge_runtime_rust::run_code_executor("import os,json;print(json.dumps(dict(os.environ)))", 5).await;
    assert_eq!(v["ok"], true, "{v}");
    let out = v["stdout"].as_str().unwrap();
    assert!(!out.contains("leak-me"), "{out}");

    let started = std::time::Instant::now();
    let v = edge_runtime_rust::run_code_executor(
        "import os,time\nif os.fork()==0:\n time.sleep(30)\nelse:\n time.sleep(30)\n",
        1,
    )
    .await;
    assert_eq!(v["error"], "code_executor_timeout");
    assert!(started.elapsed() < Duration::from_secs(5));
}

#[tokio::test]
async fn max_runtime_seconds_stops_a_slow_model() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    tokio::spawn(async move {
        let mut held = Vec::new();
        loop {
            let (sock, _) = listener.accept().await.unwrap();
            held.push(sock);
        }
    });
    let tmp = TempDir::new().unwrap();
    let (key, pub_path) = key_and_pub(&tmp);
    let mut cfg = Config::for_test(tmp.path().join("slow"), pub_path, "slow".into());
    cfg.anthropic_api_key = "k".into();
    cfg.anthropic_base_url = format!("http://127.0.0.1:{port}");
    let registry = Registry::new(cfg.clone());
    let mut agent = registry
        .install_bundle(&build_platform_bundle("slow", &["current_time"], &key), None)
        .await
        .unwrap();
    agent.manifest.edge_constraints.max_runtime_seconds = 1;
    let started = std::time::Instant::now();
    let v = edge_runtime_rust::execute_agent(&cfg, &agent, "hi", &serde_json::json!({})).await;
    assert_eq!(v["result"]["ok"], false, "{v}");
    assert!(started.elapsed() < Duration::from_secs(4), "{v}");
}

fn tar_of(members: &[(&str, &[u8], tar::EntryType, &str)]) -> Vec<u8> {
    let mut out = Vec::new();
    {
        let mut builder = tar::Builder::new(&mut out);
        for (name, data, kind, link) in members {
            let mut header = tar::Header::new_ustar();
            header.set_size(data.len() as u64);
            header.set_mode(0o644);
            header.set_entry_type(*kind);
            // write the name raw, the builder would refuse the unsafe ones this test needs
            let raw = header.as_old_mut();
            raw.name[..name.len()].copy_from_slice(name.as_bytes());
            if !link.is_empty() {
                raw.linkname[..link.len()].copy_from_slice(link.as_bytes());
            }
            header.set_cksum();
            builder.append(&header, *data).unwrap();
        }
        builder.finish().unwrap();
    }
    out
}

fn manifest_with_slug(slug: &str, tenant: &str) -> String {
    format!(
        "name: A\nslug: {slug}\ntenant_id: '{tenant}'\nversion: 0.1.0\nmodel: m\ntemperature: 0.1\nmax_iterations: 1\nmax_tokens: 8\ntools:\n- current_time\nedge_constraints:\n  max_payload_bytes: 4096\n  max_runtime_seconds: 5\n"
    )
}

fn signed_agent(slug: &str, tenant: &str, key: &RsaPrivateKey) -> Vec<u8> {
    let y = manifest_with_slug(slug, tenant);
    let reg = tar::EntryType::Regular;
    sign_stripped(
        &[
            ("agent.yaml", y.as_bytes(), reg, ""),
            ("system_prompt.md", b"p".as_slice(), reg, ""),
        ],
        key,
    )
}

// laid out with a placeholder signature, then signed over the bytes with that entry cut out
fn sign_stripped(members: &[(&str, &[u8], tar::EntryType, &str)], key: &RsaPrivateKey) -> Vec<u8> {
    let placeholder = vec![0u8; 256];
    let mut all = members.to_vec();
    all.push(("signature.sig", &placeholder, tar::EntryType::Regular, ""));
    let mut out = tar_of(&all);
    let stripped = edge_runtime_rust::strip_signature(&out);
    let sig = SigningKey::<Sha256>::new(key.clone())
        .sign_with_rng(&mut rand::thread_rng(), &stripped)
        .to_bytes()
        .to_vec();
    // the signature entry sits right before the two closing blocks and any padding
    let span = out
        .windows(13)
        .position(|w| w == b"signature.sig")
        .expect("signature entry");
    out[span + 512..span + 512 + 256].copy_from_slice(&sig);
    out
}

#[tokio::test]
async fn unsafe_slugs_and_paths_and_links_are_refused() {
    let tmp = TempDir::new().unwrap();
    let (key, pub_path) = key_and_pub(&tmp);
    let dir = tmp.path().join("agents");
    let registry = Registry::new(Config::for_test(dir.clone(), pub_path, "x".into()));
    let reg = tar::EntryType::Regular;

    for slug in ["../../evil", "/abs", "a/b", ".dot", "a..b"] {
        let b = signed_agent(slug, "", &key);
        let err = registry.install_bundle(&b, None).await.err().unwrap().to_string();
        assert!(err.contains("slug"), "{slug} {err}");
    }

    let y = manifest_with_slug("ok-slug", "");
    for name in ["../evil", "/abs/evil", "a/../../evil"] {
        let b = sign_stripped(
            &[
                ("agent.yaml", y.as_bytes(), reg, ""),
                ("system_prompt.md", b"p".as_slice(), reg, ""),
                (name, b"owned".as_slice(), reg, ""),
            ],
            &key,
        );
        let err = registry.install_bundle(&b, None).await.err().unwrap().to_string();
        assert!(err.contains("unsafe path"), "{name} {err}");
    }

    for kind in [tar::EntryType::Symlink, tar::EntryType::Link, tar::EntryType::Char] {
        let b = sign_stripped(
            &[
                ("agent.yaml", y.as_bytes(), reg, ""),
                ("system_prompt.md", b"".as_slice(), kind, "/etc/passwd"),
            ],
            &key,
        );
        let err = registry.install_bundle(&b, None).await.err().unwrap().to_string();
        assert!(err.contains("link or device"), "{err}");
    }

    let b = sign_stripped(
        &[
            ("agent.yaml", y.as_bytes(), reg, ""),
            ("agent.yaml", y.as_bytes(), reg, ""),
        ],
        &key,
    );
    let err = registry.install_bundle(&b, None).await.err().unwrap().to_string();
    assert!(err.contains("duplicate"), "{err}");

    assert_eq!(registry.count().await, 0);
    let names: Vec<_> = std::fs::read_dir(&dir).unwrap().flatten().collect();
    assert!(names.is_empty(), "nothing is written by a refused bundle");
}

#[tokio::test]
async fn unsigned_refused_unless_allowed_and_startup_checks() {
    let tmp = TempDir::new().unwrap();
    let (_key, pub_path) = key_and_pub(&tmp);
    let y = manifest_with_slug("plain", "");
    let reg = tar::EntryType::Regular;
    let unsigned = tar_of(&[
        ("agent.yaml", y.as_bytes(), reg, ""),
        ("system_prompt.md", b"p".as_slice(), reg, ""),
    ]);
    let cfg = Config::for_test(tmp.path().join("u"), pub_path, "u".into());
    let registry = Registry::new(cfg.clone());
    let err = registry.install_bundle(&unsigned, None).await.err().unwrap().to_string();
    assert!(err.contains("unsigned"), "{err}");

    let mut open = cfg.clone();
    open.allow_unsigned = true;
    assert!(Registry::new(open).install_bundle(&unsigned, None).await.is_ok());

    assert!(edge_runtime_rust::check_startup(&cfg).is_ok());
    let mut no_key = Config::for_test(tmp.path().join("n"), tmp.path().join("missing.pem"), "n".into());
    let err = edge_runtime_rust::check_startup(&no_key).unwrap_err().to_string();
    assert!(err.contains("SIGNING_PUBKEY_PEM"), "{err}");
    no_key.allow_unsigned = true;
    assert!(edge_runtime_rust::check_startup(&no_key).is_ok());
    no_key.auth_token = String::new();
    let err = edge_runtime_rust::check_startup(&no_key).unwrap_err().to_string();
    assert!(err.contains("EDGE_AUTH_TOKEN"), "{err}");
}

#[tokio::test]
async fn tenant_slug_mismatch_reload_and_failed_install_keep_old_version() {
    let tmp = TempDir::new().unwrap();
    let (key, pub_path) = key_and_pub(&tmp);
    let dir = tmp.path().join("agents");
    let mut cfg = Config::for_test(dir.clone(), pub_path, "t".into());
    cfg.tenant_id = "tenant-a".into();
    let registry = Registry::new(cfg.clone());

    let foreign = signed_agent("theirs", "tenant-b", &key);
    let err = registry.install_bundle(&foreign, None).await.err().unwrap().to_string();
    assert!(err.contains("tenant-b") && err.contains("tenant-a"), "{err}");

    let own = signed_agent("mine", "tenant-a", &key);
    let err = registry.install_bundle(&own, Some("other")).await.err().unwrap().to_string();
    assert!(err.contains("other"), "{err}");
    let first = registry.install_bundle(&own, Some("mine")).await.unwrap();

    let mut tampered = own.clone();
    tampered[600] ^= 1;
    assert!(registry.install_bundle(&tampered, Some("mine")).await.is_err());
    assert_eq!(registry.get("mine").await.unwrap().digest, first.digest);

    let fresh = Registry::new(cfg.clone());
    fresh.reload_from_disk().await;
    assert_eq!(fresh.get("mine").await.unwrap().digest, first.digest, "real digest after a restart");

    let saved = dir.join("mine").join(edge_runtime_rust::SAVED_BUNDLE);
    let mut raw = std::fs::read(&saved).unwrap();
    raw[600] ^= 1;
    std::fs::write(&saved, raw).unwrap();
    let after_tamper = Registry::new(cfg);
    after_tamper.reload_from_disk().await;
    assert!(after_tamper.get("mine").await.is_none(), "a tampered volume stays out");
}

#[test]
fn slug_rules_topics_and_mqtt_url() {
    assert!(edge_runtime_rust::valid_slug("pump-watch_1.2"));
    for bad in ["", ".a", "a/b", "a..b", "a b", "../x", &"x".repeat(96)] {
        assert!(!edge_runtime_rust::valid_slug(bad), "{bad}");
    }
    assert_eq!(edge_runtime_rust::deploy_topic("gw", "+"), "edge/gw/deploy/+");
    assert_eq!(edge_runtime_rust::ack_topic("gw", "a"), "edge/gw/ack/a");
    assert_eq!(
        edge_runtime_rust::parse_mqtt_url("mqtt://u:p@broker:1884"),
        ("broker".to_string(), 1884, Some(("u".to_string(), "p".to_string())))
    );
    assert_eq!(edge_runtime_rust::parse_mqtt_url("mqtt://broker"), ("broker".to_string(), 1883, None));
}
