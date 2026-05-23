# Edge runtime deployment

> When the cloud is too far away. Edge runtimes execute agents locally on factory floors, branch offices, vehicles, gateways. They register with the cloud and ship audit asynchronously.

---

## When to use the edge

Cloud-only is the default. Push to the edge when one of these holds:

| Reason | Example |
|---|---|
| **Latency** — sub-100ms required | On-device sensor anomaly scoring in industrial IoT |
| **Data residency** — local laws forbid sending raw data out | EU healthcare claims processing |
| **Connectivity** — intermittent or no internet | Ships, rigs, mines, vehicles |
| **Air-gap** — security perimeter forbids outbound | Defense, critical infra |
| **Cost** — egress bandwidth dominates | Camera / lidar / continuous-telemetry pipelines |

If none of those apply, run in the cloud — edge brings real operational complexity.

---

## Three edge runtimes

```mermaid
flowchart TB
  subgraph LIBS["Edge runtime variants"]
    P[edge-runtime · Python]
    R[edge-runtime-rust]
    C[edge-runtime-c]
  end

  subgraph TARGETS["Typical targets"]
    PT[x86_64 servers · K3s clusters]
    RT[ARM SoCs · NVIDIA Jetson · low-latency]
    CT[Embedded · microcontrollers · ARM Cortex-M]
  end

  P --> PT
  R --> RT
  C --> CT
```

| Runtime | Language | Footprint | Use |
|---|---|---|---|
| `edge-runtime` | Python 3.12 | ~300MB image | Default — same agent loop code as cloud, runs on K3s / k0s |
| `edge-runtime-rust` | Rust | ~12MB static binary | Low-latency streaming inference (AIS scoring, telemetry alerts) |
| `edge-runtime-c` | C | ~600KB binary | Embedded gateways with no Docker (raw ELF on the SoC) |

Source: [`apps/edge-runtime/`](../../apps/edge-runtime/), [`apps/edge-runtime-rust/`](../../apps/edge-runtime-rust/), [`apps/edge-runtime-c/`](../../apps/edge-runtime-c/).

### Picking a runtime — decision matrix

| Aspect | Python | Rust | C |
|---|---|---|---|
| **Build time** (clean) | <1s if image cached, ~2min cold | ~5min (cargo + linker) | ~10min (cross-compile + embedded toolchain) |
| **Cold-start latency** (pod ready → first event) | ~8s | <100ms | <10ms |
| **Steady-state RAM** | 150MB baseline + ~10MB per cached agent | ~25MB total + ~1MB per agent | ~3MB total + ~10KB per agent |
| **Bundle overhead** (per agent in cache) | ~50KB | ~10KB | ~10KB inline |
| **Max concurrent agents** | 1-10 (Python GIL + per-agent state) | 1-20 (Tokio async) | 1 (single-threaded by design) |
| **Hardware floor** | x86_64 or ARM64 with ≥256MB RAM, Docker | ARMv7+ with ≥64MB RAM, no Docker needed | Cortex-M4+ with ≥32MB RAM, bare metal |
| **Best for** | Dev cycle speed, typical IoT gateways, K3s-managed fleets | Low-latency telemetry, edge inference under 50ms p99, large fleets where image-pull cost matters | Bare-metal industrial controllers, where Docker isn't available, or where size below 1MB is required |
| **Worst for** | Cortex-M class chips, ultra-low latency | Rapid iteration without a build pipeline | Anything that needs multi-agent concurrency |

The Python edition is the default choice. Move to Rust when cold-start latency or pod-pull bandwidth bites. Move to C only when the device cannot run Docker at all.

---

## How an edge node works

```mermaid
sequenceDiagram
  participant E as edge node
  participant C as cloud abenix-api
  participant L as local LLM (optional)
  participant T as local tool
  participant U as user / local sensor

  Note over E: Boot
  E->>C: POST /api/edge/register<br/>{node_id, capabilities, location}
  C-->>E: registration_token + assigned agents

  loop heartbeat every 30s
    E->>C: POST /api/edge/heartbeat<br/>{node_id, health, queue_depth, last_event_id}
    C-->>E: 200, agent_updates if any
  end

  loop on local trigger
    U->>E: emit event (sensor reading / scheduled / user)
    E->>L: chat (or remote if no local LLM)
    L-->>E: response
    E->>T: tool calls (local-only tools)
    T-->>E: ToolResult
    E->>E: append to execution row (local SQLite)
  end

  loop async ship to cloud
    E->>C: POST /api/edge/executions/bulk-upload<br/>(once connectivity allows)
    C-->>E: ack + clear local
  end
```

The edge node holds its own SQLite database for the in-flight execution log. it ships completed executions to the cloud Postgres in batches.

---

## Bootstrapping a new edge node

1. **Provision the node** — install Docker / K3s / native binary depending on variant.
2. **Generate a registration token** in the cloud UI: `/admin/edge → New Edge Token`.
3. **Drop the config** at the node:
   ```bash
   cat > /etc/abenix-edge.env <<EOF
   ABENIX_API_URL=https://api.example.com
   EDGE_REGISTRATION_TOKEN=ed_***
   EDGE_NODE_ID=factory-13-line-2
   EDGE_LOCATION="Plant 13, Line 2, Munich"
   LOCAL_LLM_URL=http://ollama:11434     # optional
   ALLOWED_AGENTS=iiot-rul-estimator,iiot-cold-chain-corrector
   EOF
   ```
4. **Start the runtime**:
   ```bash
   # Python (Docker)
   docker run -d --name abenix-edge --env-file /etc/abenix-edge.env \
     your-acr.azurecr.io/edge-runtime:1.5.5

   # Rust (static binary)
   /usr/local/bin/abenix-edge-rust --config /etc/abenix-edge.env

   # C (embedded)
   /opt/abenix/edge --config /etc/abenix-edge.env
   ```
5. **Verify** — the cloud UI's `/admin/edge` shows the node with a heartbeat timestamp.

---

## Agent bundle compilation, signing, and OTA delivery

This is the path a cloud-authored agent takes to land on an edge node and start running.

### Compilation

Compilation runs in `apps/api/app/services/edge_bundle.py` whenever an agent is marked `edge_compatible: true` and assigned to one or more edge nodes:

1. **Validate tool allow-list.** The agent's `model_config.tools` must be a subset of `{mqtt_publish, mqtt_subscribe, current_time, windowed_state, connector_call, code_executor, opcua_read, opcua_write}`. Any tool outside this list — `knowledge_search`, `atlas_query`, `database_query`, etc. — fails compilation with `EDGE_TOOL_NOT_PERMITTED`.
2. **Inline KB / Atlas references.** If the agent references a knowledge base, the relevant chunks are flattened into the bundle as static lookup tables. Atlas refs become inlined node lists. This is why `knowledge_search` is forbidden — the edge has no network path back to cloud KB.
3. **Serialize.** The agent + system prompt + tool config + model name go into a Protobuf message (schema in `proto/edge_agent.proto`). Output is roughly 5-50KB depending on prompt size and inlined KB volume.
4. **Sign.** The compile service computes `SHA-256(bundle_bytes)` and signs the digest with the tenant's private RSA-2048 key (stored in the `tenant_secrets` table, AES-256 encrypted at rest with the platform's KEK). The signature is appended to the bundle as a separate `.sig` blob.

### Delivery via MQTT

The cloud uses MQTT (Mosquitto in-cluster, broker URL `mosquitto:1883`) for fan-out to edge nodes because plants typically already have a broker on-prem the edge nodes can also subscribe to during disconnected operation.

```
abenix/edge/{node_id}/register                  ← (response to POST /api/edge/register)
abenix/edge/{node_id}/heartbeat                 ← edge → cloud, every 30s
abenix/edge/{node_id}/agent/{agent_slug}        ← cloud → edge, agent bundle + sig (OTA push)
abenix/edge/{node_id}/agent/{agent_slug}/ack    ← edge → cloud, ack of load
abenix/edge/{node_id}/event/{event_type}        ← edge → cloud, decision logs, alerts
abenix/edge/{node_id}/command/{command}         ← cloud → edge, ad-hoc commands (kill, reload)
```

Payload schema for the agent topic:

```json
{
  "agent_slug": "iiot-rul-estimator",
  "version": "1.4.2",
  "bundle_b64": "<base64 of the protobuf bundle>",
  "signature_b64": "<base64 of the RSA-2048 signature>",
  "tenant_public_key_fingerprint": "sha256:...",
  "issued_at": "2026-05-23T08:14:00Z"
}
```

### Verification on the edge

When the edge runtime receives an agent message:

1. Look up the tenant's public key by fingerprint (cached on first registration, refreshed daily).
2. Compute `SHA-256(bundle_b64_decoded)`.
3. Verify with the tenant's public key: `openssl dgst -sha256 -verify pub.pem -signature sig.bin bundle.bin`.
4. On failure: drop the message, log `EDGE_AGENT_SIGNATURE_INVALID`, keep the previous version running.
5. On success: replace the agent in the local registry, ack via `/ack` topic, drain the previous version's in-flight executions.

### Crypto details

- **Algorithm:** RSA-PSS-2048 with SHA-256. Compatible with most hardware security modules (HSMs) for tenants that want private keys held outside Postgres.
- **Key rotation:** swap a tenant's RSA key in `tenant_secrets`. Edge nodes detect mismatch on the next agent push (signature verification fails), pull the new fingerprint, refresh, retry.
- **Replay attacks:** prevented by the `issued_at` field. Bundles older than 1h from the edge's local clock are rejected.

---

## Local LLM support

The Python + Rust edge runtimes support **local LLM endpoints** via the OpenAI-compatible API (Ollama, llama.cpp server, vLLM). Set `LOCAL_LLM_URL`.

```yaml
# in an agent yaml — pin to a local model
model_config:
  model: ollama/qwen2.5:7b
  llm_endpoint: http://ollama:11434/v1
```

When `model` starts with `ollama/`, `local/`, or `vllm/`, the runtime routes to `LOCAL_LLM_URL` instead of the cloud LLM. The C runtime doesn't support LLMs — it's for tool-only agents (deterministic computations on sensor data).

---

## Tool subset

Not all cloud tools work at the edge. The edge runtime ships a curated subset:

| Tool | Cloud | Edge (Python) | Edge (Rust) | Edge (C) |
|---|---|---|---|---|
| `eia_open_data` | yes | yes (needs internet) | yes | no |
| `yahoo_finance` | yes | yes | yes | no |
| `tavily_search` | yes | yes | no | no |
| `ml_model` | yes | yes (local pkl) | yes (onnx only) | yes (onnx only) |
| `kb_search` | yes | no (no Neo4j on edge) | no | no |
| `code_executor` | yes | yes (gVisor sandbox) | no | no |
| `opcua_read` / `opcua_write` | no | **edge-only** | **edge-only** | yes |
| `mqtt_publish` / `mqtt_subscribe` | no | **edge-only** | **edge-only** | yes |
| `serial_read` (RS485, Modbus) | no | yes | yes | yes |

Edge-only tools (`opcua_*`, `mqtt_*`, `serial_*`) speak directly to industrial PLCs / sensors that have no cloud equivalent.

---

## Security model

- **TLS mutual auth** between edge and cloud (registration token signs a CSR. cloud issues a per-node cert).
- **No inbound internet** required — edge polls cloud, never the reverse.
- **Per-node allow-list** of agents — even if an edge token leaks, the attacker can only invoke whitelisted agents.
- **Audit shipping** is at-least-once + deduped via execution_id. Loss of connectivity means audit catches up later, never gets lost.

---

## Failure modes + recovery

| Failure | Behaviour |
|---|---|
| Cloud unreachable | Edge keeps running — uses last-known agent definitions cached locally. Executions queued in SQLite. |
| Node crash | systemd restarts. in-flight executions resume from SQLite. |
| Disk full | New executions rejected with `EDGE_STORAGE_FULL`. Sweeper purges old completed executions once shipped. |
| LLM endpoint down | Executions that need the LLM fail with `LLM_UNAVAILABLE`. Tool-only agents continue. |
| Bad agent update | If an updated agent yaml fails validation, edge keeps the prior version + reports back. |

---

## Observability at the edge

- `/metrics` on each runtime (Prometheus scrape — useful if you run a local Prom on the edge cluster).
- Heartbeats include health stats. cloud `/admin/edge` shows a map of edge nodes + their latencies.
- Traces are buffered locally and shipped to Tempo with the execution batch. Span timestamps preserved.

---

## Cost

- **Compute**: typically <0.5 cores + 512MB per node for the runtime itself.
- **Storage**: SQLite + local cache grows with traffic. default cap 10GB.
- **Bandwidth**: heartbeat is <1KB/req. Audit ship is the bulk — averages 50-500KB/exec.

For an industrial IoT deployment with 100 plants, 5 nodes each, 100 executions/node/day, expect ~2GB/day total egress to cloud Postgres.

---

## See also

- [03-services](../01-architecture/03-services.md) — service inventory
- [01-architecture/00-overview](../01-architecture/00-overview.md) — where edge fits
- [07-standalone-apps/03-others](../07-standalone-apps/03-others.md#industrial-iot) — Industrial-IoT uses edge most heavily
