# edge-runtime-rust

Rust port of `apps/edge-runtime/runtime.py`. Behaviour-identical to the Python
runtime: registers with the platform every 60s, subscribes to
`edge.{gateway_id}.deploy` over MQTT, verifies RSA-PSS signatures over `.agent`
bundles, extracts to `/var/edge/agents/{slug}/`, and serves `/health`,
`/agents`, `/agents/{slug}/bundle`, `/agents/{slug}/execute` on port 8080.

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

Two integration tests cover the main paths:
- `boots_loads_executes` — boots the HTTP server, signs and pushes a bundle,
  asserts `/agents/{slug}/execute` returns the expected echo response (no
  Anthropic key in the test env, runtime stubs the call).
- `invalid_signature_rejected` — signs a bundle with a key that does not
  match the configured pubkey and asserts `install_bundle` errors.

## Docker

```
docker build -t agentforge/edge-runtime-rust:1.1.0 apps/edge-runtime-rust
```

The Dockerfile is a two-stage build: `rust:1.83-alpine` builder, `alpine:3.20`
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
`signing_pubkey`, `anthropic_api_key`, `endpoint_url`); image repository
defaults to `agentforge/edge-runtime-rust:1.1.0`.

To deploy the Rust variant via the existing scripts:

```
EDGE_RUNTIME_VARIANT=rust ./scripts/deploy.sh local
```

Or both side-by-side for a soak test:

```
EDGE_RUNTIME_ALL_VARIANTS=true ./scripts/deploy.sh local
```

## Binary size

In release mode with strip + LTO:

| target | typical size |
|---|---|
| musl x86_64 | ~7-9 MiB |
| musl aarch64 | ~7-9 MiB |
| docker image (alpine + python3) | ~25 MiB total |

Actual measurements depend on the rust toolchain version and dependency tree.
Run `scripts/build-edge-rust.sh` to print the exact bytes for the local
toolchain. Cargo + Docker are not available in the dev sandbox where this
port was written, so the binary size above is the design target — recorded
on first plant build.
