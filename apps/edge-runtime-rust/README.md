# edge-runtime-rust

Rust port of `apps/edge-runtime/runtime.py`. It registers with the platform every
60 s, subscribes to `edge/{gateway_id}/deploy/+` over MQTT at QoS 1, verifies
RSA-PSS signatures over `.agent` bundles, swaps them into
`/var/edge/agents/{slug}/`, and serves `/health`, `/agents`,
`/agents/{slug}/bundle` and `/agents/{slug}/execute` on port 8080, the last two
behind `EDGE_AUTH_TOKEN`. An agent makes one model call and returns the text,
there is no tool loop. It has no gateway mode. It refuses to start without a
signing key and a token, see
[the deployment guide](../../docs/06-deployment/05-edge-runtime.md).

## Why a Rust port

Plants run x86_64 Linux on rugged industrial PCs and ARM64 on edge gateways
(Siemens RUGGEDCOM, Moxa UC-8580, Raspberry Pi 4/5, NVIDIA Jetson). A single
static binary with no Python interpreter is a major maintainability win.

## Build

```
./scripts/build-edge-rust.sh
```

Or directly:

```
cd apps/edge-runtime-rust
cargo build --release --bin edge-runtime
strip target/release/edge-runtime
```

The Cargo profile uses `lto = "fat"`, `codegen-units = 1`, `opt-level = "z"`,
`panic = "abort"`, and `strip = true` to minimise binary size.

## Test

```
cd apps/edge-runtime-rust
cargo test
```

`tests/smoke.rs` covers the HTTP server and its token, signatures, tenant pinning,
unsafe slugs and tar entries, the saved bundle on restart, `params.code` and
`max_runtime_seconds`. The image is 83 MB and the binary 3.2 MB on arm64.

## Docker

```
docker build -t localhost:5000/abenix/edge-runtime-rust:latest apps/edge-runtime-rust
```

The Dockerfile is a two-stage build: `rust:1.90-alpine` builder, `alpine:3.20`
runtime with `python3` (for the `code_executor` tool) and `ca-certificates`
only.

## Supported targets

| Target triple | Use case |
|---|---|
| `x86_64-unknown-linux-musl` | rugged industrial PCs (default Docker target) |
| `aarch64-unknown-linux-musl` | ARM64 edge gateways, Raspberry Pi 4/5, Jetson |
| `armv7-unknown-linux-musleabihf` | older ARMv7 hardware (Moxa UC-8112) |

Cross-compile via `cargo build --release --target=<triple>` after installing
the toolchain with `rustup target add <triple>`.

## Helm

The matching chart lives at `infra/helm/edge-runtime-rust/`. Same value shape
as the Python chart (`gateway_id`, `platform_url`, `platform_token`, `mqtt_url`,
`signing_pubkey`, `auth_token`, `anthropic_api_key`, `endpoint_url`). It has no gateway mode. Image repository
defaults to `localhost:5000/abenix/edge-runtime-rust:latest`.

To deploy the Rust variant via the existing scripts:

```
EDGE_RUNTIME_VARIANT=rust ./scripts/deploy.sh local
```

Or both side-by-side for a soak test:

```
EDGE_RUNTIME_ALL_VARIANTS=true ./scripts/deploy.sh local
```

## Binary size

Measured on a local arm64 build, the binary is 3.2 MB and the image with `python3` is
83 MB. Idle with no agent it holds 1.5 MiB. Run `scripts/build-edge-rust.sh` to print
the bytes for your own toolchain.
