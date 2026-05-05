use std::sync::Arc;

use anyhow::Result;
use edge_runtime_rust::{mqtt_loop, register_loop, run_http, AppState, Config, Registry};

#[tokio::main(flavor = "multi_thread")]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    let cfg = Arc::new(Config::from_env());
    let registry = Arc::new(Registry::new((*cfg).clone()));
    registry.reload_from_disk().await;

    let port = cfg.port;
    let state = AppState {
        cfg: cfg.clone(),
        registry: registry.clone(),
    };

    tokio::spawn(register_loop(cfg.clone()));
    tokio::spawn(mqtt_loop(cfg.clone(), registry.clone()));

    run_http(state, port).await
}
