# edge-runtime-c

C port of `apps/edge-runtime/` for ultra-constrained plant gateways. Same wire
contract: same `.agent` bundle format, same HTTP routes, same MQTT topic, same
register POST. Drop-in replacement when the target box won't accept a Python
or Rust runtime.

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
| Embedded Linux   | 4.x+    | musl or glibc; needs ~12 MB RAM resident                |

## Build

```sh
make release           # produces build/release/edge-runtime-c
make debug             # build/debug/edge-runtime-c with -O0 -g
make clean
```

Required dev packages:

| distro  | packages                                                                         |
|---------|----------------------------------------------------------------------------------|
| alpine  | `gcc musl-dev make pkgconf curl-dev json-c-dev libmicrohttpd-dev mosquitto-dev openssl-dev zlib-dev` |
| debian  | `gcc make pkg-config libcurl4-openssl-dev libjson-c-dev libmicrohttpd-dev libmosquitto-dev libssl-dev zlib1g-dev` |
| openwrt | `gcc make pkg-config libcurl-dev libjson-c-dev libmicrohttpd-dev libmosquitto-dev libopenssl-dev zlib-dev`         |

## Binary size

`make release` strips and produces a ~43 KB binary on alpine musl x86_64.
The Docker image is alpine + the runtime libs + python3 (24 MB on its own,
needed for the `code_executor` tool) and lands around 60 MB single-arch on
disk. Drop the `python3` apk if `code_executor` isn't needed and the image
falls to ~36 MB. Without libmicrohttpd the floor is ~14 MB.

## Container build

```sh
docker build -t agentforge/edge-runtime-c:1.1.0 .
docker images agentforge/edge-runtime-c:1.1.0
```

## Run

```sh
GATEWAY_ID=plc-floor-3 \
  PLATFORM_URL=http://api.abenix:8000 \
  PLATFORM_TOKEN=$EDGE_TOKEN \
  MQTT_URL=mqtt://broker:1883 \
  SIGNING_PUBKEY_PATH=/etc/edge/signing_pub.pem \
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
| `/agents/{slug}/bundle`      | POST   | install a `.agent` bundle from the request body      |
| `/agents/{slug}/execute`     | POST   | run the agent — body `{"message":"...", "params":{}}` |

## Test

```sh
make release
bash tests/test_smoke.sh
```

The smoke test boots the binary, generates a real signed bundle, pushes it
over `/agents/{slug}/bundle`, and asserts the stub `echo` path comes back
with `duration_ms`.

## Tool whitelist

Manifest validation rejects anything outside:

- `mqtt_publish`, `mqtt_subscribe`
- `current_time`
- `windowed_state`
- `connector_call`
- `code_executor` — runs as `python3 -c "$code"` with `alarm(5)`

`atlas_*` and `mcp_*` are explicitly forbidden.

## Known gaps

- Signature verification strips the `signature.sig` blocks from the tar and
  verifies the remainder. The Python runtime instead rebuilds a fresh tar
  from the non-sig members and verifies that. The two byte streams differ
  in their trailing record-padding, so a Python-signed bundle won't
  validate against the C runtime today (and vice versa). Either:
  (a) sign at the bundle compiler against the byte-stripped form, or
  (b) extend the C runtime to also try a deterministic rebuild path before
  rejecting. The smoke test uses option (a).
- Local model_weights/ inference is rejected with `phase_2: true`, matching
  the Python runtime's v1.1 behaviour.
- The `windowed_state` and `connector_call` tools are accepted in the tool
  whitelist but not yet implemented as host-side shims; an agent that
  invokes them through the Anthropic tool-use loop gets the model's tool
  call without execution. Add shims in `executor.c` once the contract is
  pinned.
