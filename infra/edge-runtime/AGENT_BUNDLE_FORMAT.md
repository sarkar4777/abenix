# `.agent` Bundle Format — v1

The `.agent` file is the unit of deployment from AgentForge to an edge gateway.
It's a plain gzipped tarball with a fixed layout, a manifest, an optional
inline-tool directory, an optional model-weight slot, and a detached signature.

## File layout

```
my-agent.agent      (== gzipped tar)
├── agent.yaml          required — manifest (see Manifest schema)
├── system_prompt.md    required — prompt body, UTF-8
├── tools/              optional — *.py for inline code-executor tools
│   └── *.py
├── model_weights/      optional — reserved for Phase-2 distilled local model
│   └── *
└── signature.sig       required — RSA-PSS signature, see Signature
```

Anything not in that list is rejected by the runtime on load.

## Manifest schema (`agent.yaml`)

| field | required | type | notes |
|---|---|---|---|
| `name` | yes | str | human-readable name |
| `slug` | yes | str | `[a-z0-9_-]+`, unique on the gateway |
| `version` | yes | str | semver, e.g. `1.0.0` |
| `model` | yes | str | provider model id, e.g. `claude-sonnet-4-5-20250929`; ignored if `model_weights/` is present |
| `temperature` | yes | float | 0.0 to 2.0 |
| `max_iterations` | yes | int | 1 to 50; tool-use loop ceiling |
| `max_tokens` | yes | int | 1 to 200000 |
| `tools` | yes | list[str] | edge-safe tool names only; see Edge-safe tools |
| `edge_constraints` | yes | object | runtime caps; see below |
| `description` | no | str | optional UI hint |
| `system_prompt_path` | no | str | defaults to `system_prompt.md` |

### `edge_constraints`

| field | required | type | notes |
|---|---|---|---|
| `max_payload_bytes` | yes | int | per-request body cap, default 65536 |
| `max_runtime_seconds` | yes | int | per-execution wall clock cap, default 30 |
| `mqtt_subscribe` | no | list[str] | topic patterns the agent may subscribe to |
| `mqtt_publish` | no | list[str] | topic patterns the agent may publish to |

The runtime enforces these by configuration; an agent that calls
`mqtt_publish` to a topic outside `mqtt_publish[]` gets a permission denial,
not a silent succeed.

## Edge-safe tools

Allowed (will be implemented or shimmed in the runtime):

- `mqtt_publish`
- `mqtt_subscribe`
- `current_time`
- `windowed_state` — backed by local Redis if reachable, else in-memory
  TTL dict (last-write wins, no cross-pod replication)
- `connector_call` — only if the gateway's helm values pre-seed the
  connector definition; otherwise tool errors at first call
- `code_executor` — inline Python in `tools/*.py`, run in a subprocess
  with no network and a 5-second wall clock

Forbidden — the bundle compiler refuses to pack an agent referencing any of
these:

- `knowledge_search`, `kb_query`, anything that needs the platform DB
- `atlas_*` (graph ops require platform Neo4j)
- `human_approval`, `approval_gate` (needs platform `approvals` table)
- `agent_step`, `pipeline_*` (multi-agent orchestration is platform-only)
- `mcp_*`, MCP tool calls (require platform MCP registry)

The compiler runs the validation; the runtime double-checks the manifest on
load and refuses to register an agent with disallowed tools.

## Signature

```
signature.sig   = RSA-PSS(SHA-256(bundle_without_signature_sig), private_key)
mgf             = MGF1-SHA-256
salt_length     = 32
public_key      = shipped to the runtime via helm value `signing_pubkey` (PEM)
```

Algorithm details:

1. Compiler builds the tarball with `signature.sig` omitted.
2. `digest = sha256(bytes_of_tar)`.
3. `signature.sig = RSA-PSS-Sign(digest, signing_key)`.
4. Compiler appends `signature.sig` to the tarball and writes the final
   `.agent` file.

On the edge runtime:

1. Read the tarball, split out `signature.sig`.
2. Re-compute `sha256` of the remaining bytes.
3. Verify the signature against the configured public key.
4. Reject the bundle if verification fails — no fallback, no warning, the
   pod logs a `bundle_signature_invalid` event and ignores the deployment.

Rotating the signing key is a helm upgrade with the new `signing_pubkey`;
in-flight bundles signed by the old key remain trusted until the rollout
completes (StatefulSet does this serially).

## Bundle digest

The platform's `POST /api/edge/gateways/{id}/deploy` returns
`{deployed: true, bundle_digest: "<hex sha256 of full tarball>"}`. The same
digest is what the runtime logs on successful load — operators reconcile by
matching strings.

## Version compatibility

Bundle format version is implicit in the manifest's structure today. A
`bundle_format_version: 2` field will be added at the top of `agent.yaml`
when an incompatible change lands; the runtime defaults to `1` when absent.
