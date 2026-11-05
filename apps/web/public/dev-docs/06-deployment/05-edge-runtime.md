# Edge runtime deployment

> Gateways that run agents on site, next to the equipment. They register with the platform, receive signed `.agent` bundles over MQTT or HTTP, and answer execute calls by calling a model.

---

## When to use the edge

Cloud-only is the default. Push to the edge when one of these holds:

| Reason | Example |
|---|---|
| **Latency** | Scoring a sensor reading next to the machine |
| **Data residency** | Raw data may not leave the site |
| **Connectivity** | The site is often offline |
| **Cost** | Egress for continuous telemetry dominates |

If none of those apply, run in the cloud. The edge adds real operational work.

---

## What an agent on the edge can and cannot do

Read this before you plan a site around it.

- **An edge agent makes one model call and returns the text.** No edge runtime has a tool loop. The bundle carries tool names only, with no definitions and no code to run them, and the request to the model has no `tools` field. The tool list is checked when a bundle loads and it gates `params.code`, nothing more. `max_iterations` is carried and not used.
- **The model is not on the box.** Every answer needs an Anthropic Messages endpoint. With the site offline, an agent answers only if `ANTHROPIC_BASE_URL` points at an Anthropic compatible server on the site network. Without one, execute returns an error and collection carries on. Local `model_weights/` are refused, local inference is not shipped.
- **What keeps working with no link to the platform.** Loaded agents keep their prompts on disk and keep answering when the model endpoint is reachable. A restart reloads them from the volume, with the signature checked again. Abenix Edge keeps collecting into its buffer and backfills in order. `scripts/edge-e2e.sh` checks all of this on real pods.
- **What does not exist.** Agents do not listen on MQTT for input and do not publish results over MQTT. `mqtt_subscribe` and `mqtt_publish` in `edge_constraints` are carried and not enforced because nothing on the gateway publishes on an agent's behalf. Gateways keep no execution log and ship nothing back.

---

## Three runtimes, and two products in one of them

| | Python `edge-runtime` | Rust `edge-runtime-rust` | C `edge-runtime-c` |
|---|---|---|---|
| Source | [`apps/edge-runtime`](../../apps/edge-runtime/) | [`apps/edge-runtime-rust`](../../apps/edge-runtime-rust/) | [`apps/edge-runtime-c`](../../apps/edge-runtime-c/) |
| Agent bundles, the legacy mode | yes | yes | yes |
| Abenix Edge, the gateway mode with enrolment, collectors and store and forward | yes | no | no |
| Image size | 286 MB | 83 MB | 96 MB |
| Binary | n/a | 3.2 MB | 67 KB |
| Memory, idle with no agent | 24 MiB | 1.5 MiB | 3 MiB |

Sizes are from local arm64 builds, `docker images` and `docker stats`, on Abenix 2.5.10. The Rust and C images carry `python3` for `code_executor`, which is most of their size. The Python mode comes from `EDGE_MODE`, `legacy` or `gateway`. With no `EDGE_MODE` it follows the older rule, `PLATFORM_*` set and no earlier enrolment means legacy.

All three accept the same bundle and serve the same routes on port 8080.

| Route | Method | Token | What it does |
|---|---|---|---|
| `/health` | GET | no | Status, loaded agents, gateway id |
| `/agents` | GET | no | Loaded agents with slug, digest and tools |
| `/agents/{slug}/bundle` | POST | yes | Install a bundle from the request body. The slug must match the manifest |
| `/agents/{slug}/execute` | POST | yes | Run the agent. Body `{"message": "...", "params": {}}` |

### Secure by default

A gateway refuses to start without a signing key unless `EDGE_ALLOW_UNSIGNED` is the literal `true`, and without `EDGE_AUTH_TOKEN` unless `EDGE_ALLOW_NO_AUTH` is the literal `true`. Both escapes are for local development.

| Control | Behaviour |
|---|---|
| Bundle install and execute | `Authorization: Bearer <EDGE_AUTH_TOKEN>`, compared in constant time. The chart makes a token on first install and keeps it across upgrades |
| Signature | RSA-PSS with SHA-256. Unsigned, tampered and wrongly signed bundles are refused. The saved bundle is verified again on every restart |
| Tenant | With `TENANT_ID` set, a bundle for another tenant is refused. An enrolled gateway takes this from its enrolment |
| Slug and tar paths | Slugs are `[A-Za-z0-9][A-Za-z0-9._-]*` with no `..`. Tar entries must be plain files or folders under safe relative names, so traversal, links, devices and duplicates refuse the whole bundle. Nothing is written for a refused bundle |
| Install | Written beside the live folder and swapped, so a failed install leaves the old version serving |
| `params.code` | Off until `EDGE_ENABLE_CODE_EXECUTOR` is the literal `true`, and the agent must list `code_executor`. Then `python3 -I` with no shell, only `PATH` and `HOME` in its environment, its own process group and a limit of 5 seconds or `max_runtime_seconds`, whichever is shorter |
| `max_runtime_seconds` | Enforced on the whole execute, which answers `{"ok": false, "error_code": "max_runtime_exceeded"}` |

`max_payload_bytes` is enforced too. The broker is outside this, see [MQTT](#mqtt).

Each chart ([`edge-runtime`](../../infra/helm/edge-runtime/values.yaml), [`-rust`](../../infra/helm/edge-runtime-rust/values.yaml), [`-c`](../../infra/helm/edge-runtime-c/values.yaml)) is a StatefulSet with a persistent volume and a Service on 8080, a read only root filesystem and no capabilities. The image default is `localhost:5000/abenix/<variant>:latest`, what `deploy.sh` builds on minikube. `deploy-azure.sh` never builds them and pulls `:latest` from ACR unless `EDGE_IMAGE_TAG` is set, so push the image first. See [01-images](01-images.md#edge-runtime-images).

---

## How a gateway works

```mermaid
sequenceDiagram
  participant G as gateway
  participant A as abenix-api
  participant M as MQTT broker

  loop every 60s
    G->>A: POST /api/edge/gateways/register<br/>{gateway_id, name, endpoint_url}
    A-->>G: gateway row, status online
  end
  G->>M: subscribe edge/<gateway_id>/deploy/+ at QoS 1
  Note over A: user deploys an agent to the gateway
  A->>A: compile and sign the bundle
  A->>M: publish edge/<gateway_id>/deploy/<slug><br/>QoS 1, retained
  M-->>G: bundle bytes, now or when it next connects
  G->>G: verify, check the manifest, swap into /var/edge/agents/<slug>
  G->>M: edge/<gateway_id>/ack/<slug>, ok or the reason it refused
  M-->>A: the answer, waited on for 5 s
  Note over A,G: no answer and an endpoint_url<br/>means POST <endpoint_url>/agents/<slug>/bundle with the push token
```

On execute a runtime checks the payload against `max_payload_bytes`, then sends one Anthropic Messages request with the bundle's system prompt, model, temperature and `max_tokens`, and returns the text. With no credential it returns `{"ok": false, "stub": true, "echo": ...}`. A subscription token goes in `ANTHROPIC_AUTH_TOKEN` or `CLAUDE_SUBSCRIPTION_TOKEN` and is sent as a bearer token. An API key wins when both are set.

### What a deploy tells you

`POST /api/edge/gateways/{id}/deploy` says what happened, not what it hoped.

| Field | Meaning |
|---|---|
| `deployed` | True only when the gateway itself said it loaded the bundle, an MQTT answer or a 2xx from its endpoint |
| `delivered_via` | `mqtt`, `http`, or null when neither confirmed |
| `queued` | The broker accepted it and holds it retained, the gateway loads it when it next connects. The answer is still 200 |
| `gateway_reachable` | True when the gateway answered anything, false when it did not, null when there was nothing to try |
| `refused` | The gateway read the bundle and said no. The retained copy is removed so it does not come back |
| `message`, `mqtt`, `http`, `topic`, `bundle_digest`, `bundle_bytes` | The reason in words and each attempt in detail |

Nothing confirmed and nothing queued answers 502 `GATEWAY_UNREACHABLE`. A refusal answers 422 `GATEWAY_REFUSED`. Both carry the same fields under `error.details`. A gateway's HTTP token is set with `PATCH /api/edge/gateways/{id}` and `{"push_token": "..."}`. It is stored encrypted and never returned, `push_token_set` says whether there is one. The install step makes one for a gateway with the agents role.

### MQTT

Bundles use QoS 1 and are retained, one topic per agent, so a gateway that was off at publish time gets every agent when it connects. Retained bundles hold system prompts and sit on the broker, and the in-cluster mosquitto allows anonymous clients by default. Anyone who can reach it can read them. Signatures stop a forged bundle, not a replay of an older signed one. Turn on `auth.require_auth` on the mosquitto chart and put the login in `mqtt_url` as `mqtt://user:password@host:1883` for anything past a test cluster.

The platform knows a gateway through its register calls and the bundles it pushed, listed by `GET /api/edge/gateways` and `GET /api/edge/gateways/{id}/agents`.

---

## Platform endpoints

All under `/api/edge`.

| Method | Path | Auth | What |
|---|---|---|---|
| `GET` | `/signing-key` | none | `{public_key_pem, algorithm, dev_key}` |
| `GET` | `/runtime/download` | none | The three variants with image, chart and install hints |
| `POST` | `/tokens/mint` | signed in | New `af_*` key with `edge.register` in its scopes, plus the signing public key. The raw key is shown once |
| `POST` | `/gateways/register` | gateway token | Idempotent on `gateway_id` |
| `GET` | `/gateways` | signed in | The tenant's gateways |
| `POST` | `/gateways/{id}/deploy` | signed in | Body `{"agent_id"}`. Compile, sign, send, and say what happened, see [above](#what-a-deploy-tells-you) |
| `GET` | `/gateways/{id}/agents` | signed in | What was pushed |
| `DELETE` | `/gateways/{id}` | signed in | |
| `POST` | `/agents/{agent_id}/compile` | signed in | Compile and sign without pushing |

The UI for all of this is `/edge`.

---

## Bundle format and compilation

`apps/api/app/services/edge_compiler.py` builds a tar with:

- `agent.yaml` — name, slug, `tenant_id`, version, model, temperature, `max_iterations`, `max_tokens`, tools, `edge_constraints` (`max_payload_bytes` default 65536, `max_runtime_seconds` default 30, `mqtt_subscribe`, `mqtt_publish`), description
- `system_prompt.md`
- `signature.sig` — RSA-PSS with SHA-256, salt length 32, over the tar without the signature

Allowed tools are `mqtt_publish`, `mqtt_subscribe`, `current_time`,
`windowed_state`, `connector_call` and `code_executor`. Anything else fails
compilation, including `knowledge_search`, `kb_query`, `human_approval`,
`approval_gate`, `agent_step` and any `atlas_*`, `mcp_*` or `pipeline_*` tool.
The gateway runs the same check again before it loads a bundle.

---

## What a gateway needs

| Env var | What it is | Where it comes from | Without it |
|---|---|---|---|
| `PLATFORM_URL` | API base | your platform | Defaults to `http://host.docker.internal:8000` |
| `PLATFORM_TOKEN` | `af_*` key sent as `Authorization: Bearer` | `/edge` -> mint, or `POST /api/edge/tokens/mint` | Registration is skipped with `skip_register`. Bundles can still arrive over MQTT or HTTP |
| `SIGNING_PUBKEY_PEM` or `SIGNING_PUBKEY_PATH` | RSA public key | `GET /api/edge/signing-key`, or the mint response | Every runtime refuses to start, unless `EDGE_ALLOW_UNSIGNED` is the literal `true` |
| `EDGE_AUTH_TOKEN` | Bearer token for install and execute | you, or the chart makes one | Every runtime refuses to start, unless `EDGE_ALLOW_NO_AUTH` is the literal `true` |
| `EDGE_ENABLE_CODE_EXECUTOR` | Lets `params.code` run | you | `params.code` is refused |
| `GATEWAY_ID` / `GATEWAY_NAME` | identity | you | `edge-local` |
| `MQTT_URL` | broker for `edge/<gateway_id>/deploy/+` | your broker | Bundles only arrive over HTTP to `ENDPOINT_URL` |
| `ENDPOINT_URL` | URL the platform can reach this gateway on | your network | HTTP push has nowhere to go |
| `TENANT_ID` | pin to one tenant | a tenant UUID | Any tenant's bundle loads. With it, a foreign bundle is refused with `bundle_tenant_mismatch` |
| `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL` | the model | your key, or a server on the site network | Execute returns the stub |

Full list in [09-reference/01-env-vars](../09-reference/01-env-vars.md#edge-runtimes).

### Token lifecycle

1. **Mint.** `/edge` -> mint, or `POST /api/edge/tokens/mint`. The raw token comes back once, the platform keeps only its SHA-256.
2. **Install.** Helm `--set platform_token=<af_...>`, or the env file on a bare gateway.
3. **Rotate.** Mint a new one, upgrade the gateway, revoke the old key from the API keys page. The gateway keeps its `gateway_id`, so it re-registers as the same row.
4. **Revoke.** Deactivate or delete the key. The next register call fails.

### Signing key lifecycle

Signing fails closed. Outside dev the API never mints a key, and a gateway never loads a bundle it cannot verify.

1. **Generate.** RSA-2048, PKCS8, unencrypted. Keep the private half out of git.
   ```bash
   openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out edge_signing_priv.pem
   openssl pkey -in edge_signing_priv.pem -pubout -out edge_signing_pub.pem
   ```
2. **Install on the API.** The deploy scripts read two file paths and pass them with `--set-file`, so the multi-line PEM survives the shell.
   ```bash
   EDGE_SIGNING_KEY_FILE=./edge_signing_priv.pem \
   EDGE_SIGNING_PUBKEY_FILE=./edge_signing_pub.pem \
   bash scripts/deploy-azure.sh redeploy
   ```
   That lands as `secrets.edgeSigningKeyPem` and `secrets.edgeSigningPubkeyPem` in `abenix-secrets`, which the api pod reads as `EDGE_SIGNING_KEY_PEM` and `EDGE_SIGNING_PUBKEY_PEM`. A mounted file via `EDGE_SIGNING_KEY_PATH` works too.
3. **Distribute the pubkey.** `deploy-azure.sh` reads it from the API and passes the chart's `signing_pubkey` value, which lands at `/etc/edge/signing_pub.pem` in the gateway pod. Bare gateways can `curl` `GET /api/edge/signing-key` into that path.
4. **Rotate.** Replace the key files, redeploy, then upgrade every gateway with the new `signing_pubkey`. A bundle signed with the old key fails verification, the gateway logs `bundle_rejected` and keeps serving what it had.
5. **Verify.** `agent_loaded slug=... digest=...` on success. `bundle_rejected reason=bundle_signature_invalid` on tamper, `bundle_tenant_mismatch` on a foreign tenant.

What fails closed means in practice:

| Situation | API (`ENVIRONMENT` not a dev value) | Gateway |
|---|---|---|
| No signing key configured | `503` on compile, deploy and token mint, naming `EDGE_SIGNING_KEY_PEM` | Refuses to start without a pubkey, message names `SIGNING_PUBKEY_PEM` and the fetch endpoint |
| Unsigned bundle pushed | n/a, the API always signs | Rejected unless `EDGE_ALLOW_UNSIGNED` is the literal `true`, which is logged at startup and on every load |
| Bad or foreign signature | n/a | Rejected, logged, previous bundle keeps running |
| `tenant_id` mismatch | n/a | Rejected when `TENANT_ID` is set, both ids logged |

Dev is the one exception. With `ENVIRONMENT` set to `dev`, `development`, `local`, `test` or `testing`, or `DEBUG=true` and no `ENVIRONMENT`, the API generates a key once, stores it under the shared data dir (`<UPLOAD_DIR>/../edge/signing_priv.pem`, `/data/edge` on k8s, override with `EDGE_SIGNING_KEY_DIR`) so replicas and restarts agree, and logs one `edge_dev_signing_key` warning. `deploy.sh` passes the real signing key to the local gateway and `EDGE_ALLOW_UNSIGNED` stays off unless you set it. The Azure values use `environment: staging`, which is not a dev value, so the Azure API needs a real key.

---

## Installing a gateway

### In a cluster

`deploy.sh local` and `deploy-azure.sh deploy` install one gateway named
`edge-cluster-default` (`EDGE_GATEWAY_ID`) as the release `abenix-edge`, with
`abenix-edge-rust` and `abenix-edge-c` for the other variants and `-rust` or
`-c` added to the gateway id. `EDGE_RUNTIME_VARIANT=python|rust|c` picks the
runtime, `EDGE_RUNTIME_ALL_VARIANTS=true` installs all three, and
`EDGE_RUNTIME_ENABLED=false` skips it. Both scripts mint a platform token, pass
the signing public key and point `mqtt_url` at `abenix-mosquitto` on 1883.

For a k3s box on site:

```bash
helm upgrade --install edge-plant-13 infra/helm/edge-runtime \
  --set gateway_id=plant-13-line-2 \
  --set platform_url=https://api.example.com \
  --set platform_token=af_... \
  --set-file signing_pubkey=./edge_signing_pub.pem \
  --set mqtt_url=mqtt://broker.plant:1883 \
  --set auth_token=<a long random string> \
  --set anthropic_api_key=sk-ant-...
```

Gateway mode on the Python chart, with the token from the install step on the Edge page.

```bash
helm upgrade --install yard infra/helm/edge-runtime \
  --set mode=gateway \
  --set platform_url=https://api.example.com \
  --set enroll_token=etk_...
```

| Value | Meaning |
|---|---|
| `mode` | `legacy` or `gateway`. Rust and C refuse `gateway`. The volume name differs, so changing the mode of a release means uninstalling it first |
| `enroll_token` | The one-time `etk_` token, needed only for the first start or a re-enrolment |
| `collectors` | Specs set on the box, added to those from the platform. They sit in the chart's Secret because a spec can hold a password |
| `signing_pubkey`, `allow_unsigned` | The verify key. The chart fails without one in legacy mode. Gateway mode gets it from the enrolment |
| `auth_token`, `allow_no_auth` | The bearer token. Empty makes one and keeps it. Changing it rolls the pod |
| `mqtt_url`, `endpoint_url`, `tenant_id`, `code_executor_enabled` | As their variables above |
| `anthropic_api_key`, `anthropic_auth_token`, `existing_llm_secret`, `anthropic_base_url` | The model credential, directly or from a Secret you already have |
| `extra_env`, `extra_volumes`, `extra_volume_mounts`, `extra_containers` | Folders for file tail, devices, sidecars |

The image needs to be on the node. `bash scripts/deploy.sh edge-image` builds the Python one on minikube, and `docker build -t localhost:5000/abenix/edge-runtime-rust:latest apps/edge-runtime-rust` works the same way for the others once your shell has `minikube docker-env`.

### Docker or bare metal

```bash
cat > /etc/abenix-edge.env <<EOF
PLATFORM_URL=https://api.example.com
PLATFORM_TOKEN=af_***
EDGE_AUTH_TOKEN=<a long random string>
GATEWAY_ID=plant-13-line-2
GATEWAY_NAME=Plant 13 Line 2
MQTT_URL=mqtt://localhost:1883
ANTHROPIC_API_KEY=sk-ant-...
SIGNING_PUBKEY_PATH=/etc/edge/signing_pub.pem
EOF
curl -s https://api.example.com/api/edge/signing-key   # copy public_key_pem into /etc/edge/signing_pub.pem

docker run -d --name abenix-edge --env-file /etc/abenix-edge.env \
  -v /etc/edge:/etc/edge:ro -v edge-agents:/var/edge/agents -p 8080:8080 <registry>/edge-runtime:latest
```

The Rust and C binaries read the same variables from the environment. Run
them under systemd if you want restarts.

Check the gateway on `/edge`. Its status turns online after the first register
call.

---

## Failure modes

| Failure | Behaviour |
|---|---|
| Platform unreachable | Register retries every 60 seconds. Loaded agents keep answering when the model endpoint is reachable, and reload from the volume on restart |
| Model endpoint unreachable | Execute answers `{"ok": false, "error": ...}`. Nothing is queued or retried |
| Bad bundle | Refused and logged, the previous version keeps serving |
| Gateway off at deploy time | `queued` is true, the broker holds the bundle and the gateway loads it when it connects |
| Bundles on disk from before this version | They have no saved bundle to verify, so they do not load and the log says to push them again. A retained bundle does that by itself |
| No model credential | Execute returns the stub answer |
| Payload too large | Execute returns `payload exceeds <n> bytes` |
| Run too long | Execute stops at `max_runtime_seconds` |
| Gateway mode, hard kill | Readings are staged in memory for about a second before they reach disk, so a `SIGKILL` or a power cut can lose that second. A normal stop loses nothing |

---

## Testing it

| Command | What it needs | What it proves |
|---|---|---|
| `python -m pytest apps/edge-runtime/tests` | Python | The runtime and the gateway against fakes |
| `cargo test` in `apps/edge-runtime-rust`, `tests/test_smoke.sh` in `apps/edge-runtime-c` | The toolchain, CI runs them in Docker | The same refusals in each language |
| `bash scripts/edge-conformance.sh` | Docker | The three images, read only, with a real broker and gateway mode against a fake platform. No cluster |
| `bash scripts/deploy.sh edge-e2e` | Minikube with Abenix up, and the API rolled to this version | Real pods per variant against the real platform, MQTT at QoS 1 with a gateway offline at publish time, real model answers, persistence, the API at 0 replicas, gateway mode, every collector type, cut and backfill with a pod delete, the buffer limit, revoke and token rotation. Prints a pass, fail table, exits nonzero on any failure and restores the API on any exit. `KEEP=1` keeps the pods |

The model checks use `ANTHROPIC_API_KEY`, `anthropic-api-key` or `CLAUDE_SUBSCRIPTION_TOKEN` from the `abenix-secrets` secret, then the same names from your shell. With none set they are skipped, the run says so, and everything else still runs.

---

## See also

- [00-overview](00-overview.md) — the deploy flow
- [09-reference/01-env-vars](../09-reference/01-env-vars.md) — gateway and API variables
