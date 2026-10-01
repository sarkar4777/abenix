# Tool configuration

> Where a tool's API keys and settings come from, how an admin changes them at run time, and why a new tool shows up on the screen with no UI work.

---

## For admins

**Admin -> Tool Configuration** lists every value a built-in tool needs. One card per provider, one row per key. Each row says whether the value is set and where it comes from:

| Badge | Meaning |
|---|---|
| saved here | An admin saved it on this screen. Wins over everything below. |
| from environment | Set on the pods by the deployment (helm values or the cluster secret). |
| from tool_defaults.yaml | A default shipped in `packages/db/seeds/tool_defaults.yaml`. |
| tool default | The value the tool declared. |
| not set | Nothing provides it. |

Paste a value and **Save**. Every pod picks it up within 30 seconds, no redeploy. **Clear saved value** removes what was saved so the next source applies again. **Test**, where offered, sends one request to the provider with the value you typed and reports what the provider answered.

A row marked **required** belongs to a tool that cannot run without it. The tool answers the agent with one sentence naming the key and this screen, so a user asking an agent to do something that needs a missing key is told exactly what to ask you for. Optional rows belong to tools that run in a degraded mode without them, and the tool says so in its answer.

Secrets are masked after saving, you see the last four characters. Values are encrypted with the cluster key when one is set. The header of the screen tells you which. Without a cluster key they are stored as entered, the same way the Claude subscription token always has been, and the fix is to set `secrets.dataKeyKekBase64` in the helm values. See [06-encryption-setup](06-encryption-setup.md).

Not on this screen: MCP tools carry their credentials on the MCP connection at `/mcp`, code assets keep their own encrypted secrets at `/code-runner`, and tools an agent generates at run time cannot read configuration at all.

Where else the same information appears:

- `/tools` shows a badge per tool, "needs key", "optional key" or "key set", and a Configure link for admins.
- The builder palette shows the same badge, and the agent panel's checklist counts "tool credentials configured x/y" for the tools on the canvas.
- `/settings/integrations` lists the same keys for everyone and tells non-admins to ask an admin.

---

## For operators

Precedence, highest first:

1. a value saved on the admin screen, stored in `platform_settings` as `tool.credential.<KEY>`
2. the process environment of the pod
3. `packages/db/seeds/tool_defaults.yaml`
4. the default the tool declared

The environment is still a fine place for keys. Helm values and `.env` keep working, and the admin screen shows "from environment" for them. The screen is for the keys nobody thought of at deploy time and for rotation without a rollout.

Propagation is 30 seconds. The agent-runtime reads the table over `DATABASE_URL` with asyncpg, in a single-flight refresh that serves the previous snapshot while it runs, so a slow database never blocks a tool call. The API's own copy is refreshed on every admin read, so the admin screen is always current. Other API workers may lag by up to 30 seconds, which only matters for the badges.

Encryption at rest uses the same AES-GCM helper as persona memory, under one fixed platform scope. Set the KEK once:

```bash
export ABENIX_DATA_KEY_KEK_BASE64="$(openssl rand -base64 32)"
bash scripts/deploy.sh local            # or deploy-azure.sh redeploy
```

The chart puts it in the cluster secret and every pod gets it through `envFrom`. Keep it stable. A changed KEK makes saved values unreadable and the resolver treats them as empty, so they have to be entered again.

The deploy prints, after seeding, which seeded agents reference tools whose required keys are not set. Nothing fails, it is a reminder of what to paste into the screen.

The API endpoints, all admin only:

| Method | Path | Does |
|---|---|---|
| GET | `/api/admin/tool-config` | Every key grouped by provider, with source, masked value and the tools it unlocks |
| PATCH | `/api/admin/tool-config/{KEY}` | Save a value. Validated by kind. Returns the row |
| DELETE | `/api/admin/tool-config/{KEY}` | Remove the saved value |
| POST | `/api/admin/tool-config/{KEY}/test` | Run the declaring tool's check, with `{"value": "..."}` or the saved value |

For everyone: `GET /api/tools` carries a `config` object per tool with `status` and `fields`, never values. `GET /api/integrations/tools` is the same catalogue without values.

---

## For developers

A tool declares what it needs on the class and reads it through the resolver:

```python
class AisStreamTool(BaseTool):
    name = "ais_stream"
    config_fields = (
        ConfigField("AISSTREAM_API_KEY", label="API key", kind="secret", required=True,
                    group="AISStream", signup_url="https://aisstream.io"),
    )

    async def execute(self, arguments):
        key = self.cfg("AISSTREAM_API_KEY", required=True)
```

That is the whole contract. The API imports the runtime tool classes to read `input_schema` for the catalogue, and reads `config_fields` the same way. The admin screen renders whatever the API returns. So a tool that declares its fields is on the screen, in the badges and on the Integrations page the moment it is deployed.

What makes the contract hold is the lint, `scripts/check-tool-config.py`. It runs in CI, in `deploy.sh` before images are built, and under pytest. It fails on any `os.environ` read in a tool, on a `cfg()` key no tool declares, on a declared key nothing reads, and on a tool class the registry cannot reach. A tool that reads a key privately cannot pass CI, which is why the platform can promise that the screen is complete.

`required=True` is a strong statement. It means `cfg()` raises when nothing provides the value, the base class returns the standard "not configured" result, and a pipeline node using the tool fails. Say it only when the tool has one provider and no fallback. A tool with several sources declares each key optional and reports what it skipped in `metadata.sources_skipped` and `metadata.warnings`, which the runtime appends to what the model sees.

The LLM provider keys are declared by the `llm_call`, `llm_route` and `agent_step` tools on the router's behalf, so they sit on the same screen. The router builds each provider's client from the resolver and rebuilds it when the key changes.

Writing one: [01-add-a-tool](01-add-a-tool.md) walks through a tool with an optional key, a degraded mode, a key test and the unit tests.

---

## What the model sees

Before this mechanism a missing key produced four different behaviours across the tools, from an error to an empty list with an invented reason. Now there are two:

- **Required and missing.** The tool result is an error reading `KEY is not configured. An admin can add it under Admin -> Tool Configuration. Get a key at <url>`. The model repeats it. The Flight Recorder shows it under the tool call.
- **Optional and missing.** The tool runs on what it has and appends a tool note, for example `[tool notes] UK PSC register not queried: COMPANIES_HOUSE_API_KEY is not configured`. In a pipeline the note is also written into the node's output as `_warnings`, because the next node only sees the output.

A key the provider rejects is treated as the first case, with the provider's status code, never as an empty result.

---

## See also

- [01-add-a-tool](01-add-a-tool.md)
- [06-encryption-setup](06-encryption-setup.md)
- [09-reference/04-platform-settings](../09-reference/04-platform-settings.md), the `tool.credential.*` namespace
- [09-reference/01-env-vars](../09-reference/01-env-vars.md), the generated list of keys
