# `.agent` bundle format, version 1

The `.agent` file is the unit of deployment from Abenix to an edge gateway. It is a plain tar file, not compressed, built by `apps/api/app/services/edge_compiler.py`.

## File layout

```
my-agent.agent
├── agent.yaml        the manifest
├── system_prompt.md  the prompt, UTF-8
└── signature.sig     RSA-PSS signature
```

The compiler writes these three and nothing else. Every entry must be a plain file or folder under a safe relative name. Links, devices, absolute paths, `..` segments, backslashes and duplicate names refuse the whole bundle. A runtime that finds files under `model_weights/` refuses to run the agent, local inference is not shipped. Compressed bundles are refused.

A bundle carries no tool code and no tool definitions. It cannot, today, give a model anything to call on the device.

## Manifest schema (`agent.yaml`)

| Field | Required | Type | Notes |
|---|---|---|---|
| `name` | yes | str | Human readable name |
| `slug` | yes | str | `[A-Za-z0-9][A-Za-z0-9._-]*`, at most 95 characters, no `..`. It names the folder on the gateway, so anything else is refused |
| `tenant_id` | yes | str | The platform tenant that compiled the bundle, covered by the signature. A gateway with `TENANT_ID` set refuses any other value |
| `version` | yes | str | Such as `1.0.0` |
| `model` | yes | str | The model id sent to the Messages API |
| `temperature` | yes | float | Sent to the model |
| `max_iterations` | yes | int | Carried and not used, there is no tool loop |
| `max_tokens` | yes | int | Sent to the model |
| `tools` | yes | list | Names from the list below. Checked at load |
| `edge_constraints` | yes | object | See below |
| `description` | no | str | A hint for the UI |
| `system_prompt_path` | no | str | Always `system_prompt.md` |

### `edge_constraints`

| Field | Type | Notes |
|---|---|---|
| `max_payload_bytes` | int | Enforced on the request message, default 65536 |
| `max_runtime_seconds` | int | Enforced on the whole execute, default 30 |
| `mqtt_subscribe` | list | Carried and not enforced, agents do not use MQTT on the gateway |
| `mqtt_publish` | list | Carried and not enforced, agents do not use MQTT on the gateway |

## Tool names

`mqtt_publish`, `mqtt_subscribe`, `current_time`, `windowed_state`, `connector_call`, `code_executor`.

Listing one of these lets the bundle load. It does not give the model the tool, the model call has no `tools` field and no runtime implements them. The one effect is that `code_executor` allows `params.code` on an execute call, and only on a gateway that also sets `EDGE_ENABLE_CODE_EXECUTOR=true`.

The compiler refuses anything else, including `knowledge_search`, `kb_query`, `atlas_*`, `human_approval`, `approval_gate`, `agent_step`, `pipeline_*` and `mcp_*`. A runtime checks the list again at load.

## Signature

```
signature.sig = RSA-PSS(bundle bytes with the signature.sig entry cut out)
hash          = SHA-256
mgf           = MGF1-SHA-256
salt_length   = 32
public_key    = helm value signing_pubkey, or SIGNING_PUBKEY_PEM, or SIGNING_PUBKEY_PATH
```

The compiler lays the tar out with a zeroed `signature.sig`, signs the bytes with that entry's header and data blocks cut out, then writes the signature into place. The gateway cuts the same blocks and verifies. The Python and Rust runtimes also accept a signature over a rebuilt tar, for older bundles.

A bad or missing signature, or a gateway with no public key, refuses the bundle and the previous version keeps serving. The only bypass is `EDGE_ALLOW_UNSIGNED` set to the literal `true`, for local development, logged at start and on every load. A gateway with no key and no bypass does not start. With `TENANT_ID` set, `manifest.tenant_id` must match or the bundle is refused with `bundle_tenant_mismatch` naming both ids.

The runtime saves the received bytes as `bundle.agent` in the agent's folder and verifies them again on every restart.

Rotating the signing key is a helm upgrade with the new `signing_pubkey`. Bundles signed by the old key stop loading at the next restart, so deploy them again.

## Delivery

MQTT topic `edge/<gateway_id>/deploy/<slug>`, QoS 1, retained. The gateway answers on `edge/<gateway_id>/ack/<slug>` with `{"slug", "digest", "ok", "error"}`. An empty message clears a retained bundle and is ignored by gateways. HTTP is `POST <endpoint_url>/agents/<slug>/bundle` with `Authorization: Bearer <token>`.

## Bundle digest

`POST /api/edge/gateways/{id}/deploy` returns `bundle_digest`, the SHA-256 of the whole file, and `GET /agents` on the gateway lists the same value.
