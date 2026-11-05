# edge-runtime-c

C port of the agents half of `apps/edge-runtime/` for small plant gateways. Same
`.agent` bundle format, HTTP routes, token, MQTT topics and register call. It has
no gateway mode, so no enrolment, collectors or store and forward. An agent makes
one model call and returns the text, there is no tool loop.

## Why C

Allen-Bradley CompactLogix gateways, Beckhoff TwinCAT/BSD, Phoenix Contact
PLCnext, OpenWRT routers, and most ARM Cortex-A7/A53 boards in the field run
at 256–512 MB RAM with whatever the vendor shipped. A C binary linked against
glibc or musl plus a couple of dependable libs (libcurl, libmosquitto,
openssl, json-c, libmicrohttpd) is the realistic minimum.

## Supported targets

| target           | tested  | notes                                                  |
|------------------|---------|--------------------------------------------------------|
| Alpine 3.20 musl | yes     | image build path                                       |
| Debian 12 glibc  | yes     | install `libcurl4 libmosquitto1 libssl3 libjson-c5 libmicrohttpd12` |
| ARM Cortex-A7+   | armv7hf | cross-compile with `gcc-arm-linux-gnueabihf` + matching libs |
| ARM Cortex-A53   | aarch64 | same, with `gcc-aarch64-linux-gnu`                      |
| OpenWRT 22.03+   | yes     | install `libcurl libmosquitto-ssl libopenssl json-c libmicrohttpd` |
| Embedded Linux   | 4.x+    | musl or glibc, 3 MiB of memory idle in the Alpine image on arm64 |

## Build

```sh
make release           # produces build/release/edge-runtime-c
make debug             # build/debug/edge-runtime-c with -O0 -g
make clean
```

Required dev packages:

| distro  | packages                                                                         |
|---------|----------------------------------------------------------------------------------|
| alpine  | `gcc musl-dev make pkgconf curl-dev json-c-dev libmicrohttpd-dev mosquitto-dev openssl-dev` |
| debian  | `gcc make pkg-config libcurl4-openssl-dev libjson-c-dev libmicrohttpd-dev libmosquitto-dev libssl-dev` |
| openwrt | `gcc make pkg-config libcurl-dev libjson-c-dev libmicrohttpd-dev libmosquitto-dev libopenssl-dev`         |

## Binary size

`make release` strips and produces a 67 KB binary on Alpine musl arm64. The image
with its libraries and `python3` for `code_executor` is 96 MB.

## Container build

```sh
docker build -t localhost:5000/abenix/edge-runtime-c:latest .
```

## Run

```sh
GATEWAY_ID=plc-floor-3 \
  PLATFORM_URL=http://api.abenix:8000 \
  PLATFORM_TOKEN=$EDGE_TOKEN \
  MQTT_URL=mqtt://broker:1883 \
  SIGNING_PUBKEY_PATH=/etc/edge/signing_pub.pem \
  EDGE_AUTH_TOKEN=$EDGE_AUTH_TOKEN \
  ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  ./build/release/edge-runtime-c --port 8080
```

Same env-var contract as the Python pod. See
`infra/edge-runtime/AGENT_BUNDLE_FORMAT.md` for the bundle layout.

## HTTP routes

| route                        | method | notes                                                |
|------------------------------|--------|------------------------------------------------------|
| `/health`                    | GET    | `{status, agents, gateway_id}`                       |
| `/agents`                    | GET    | list of registered agents                            |
| `/agents/{slug}/bundle`      | POST   | needs the token, installs a `.agent` bundle from the request body |
| `/agents/{slug}/execute`     | POST   | needs the token, runs the agent, body `{"message":"...", "params":{}}` |

## Test

```sh
make release
bash tests/test_smoke.sh
```

The smoke test boots the binary with real signed bundles and checks the start
refusals, the token, tampered, unsigned, foreign tenant, traversal and symlink
bundles, the restart, `params.code` with its scrubbed environment and its limit.
Run `bash scripts/edge-conformance.sh` for the same contract next to the other runtimes.

## Tool whitelist

Manifest validation refuses anything outside `mqtt_publish`, `mqtt_subscribe`,
`current_time`, `windowed_state`, `connector_call` and `code_executor`. The model
is not given any of them. `code_executor` only opens `params.code`, and only with
`EDGE_ENABLE_CODE_EXECUTOR=true`. Then it runs as `python3 -I -c` with no shell, an
environment of `PATH` and `HOME`, its own process group and a 5 second limit.

## Known limits

- The system prompt is kept up to 16 KB, a longer one is cut and the log says so.
- At most 64 agents, 16 tools on an agent, and tar names up to 100 bytes.
- Local `model_weights/` are refused with `phase_2: true`.
- It verifies only the platform's signed view, not the older rebuilt tar the Python and Rust runtimes also accept.
