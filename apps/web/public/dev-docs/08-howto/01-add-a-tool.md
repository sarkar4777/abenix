# How to add a new tool

> From an empty file to a tool an agent can call, with its configuration on the admin screen and a test in CI. About 45 minutes.

---

## What you are building

A tool is one Python class. It declares four things and the platform does the rest:

| Declaration | Who reads it |
|---|---|
| `name` and `description` | The model, when deciding whether to call it. The catalogue at `/tools`. |
| `input_schema` | The model, to build the call. The runtime validates against it before dispatch. |
| `config_fields` | **Admin -> Tool Configuration**, which renders one row per field. The `/tools` catalogue and the builder palette, which show a credential badge. The Integrations page. The lint in CI. |
| `execute()` | The runtime. |

Nothing else needs editing when you add a tool. There is no registry of credentials in the API, no list in the web app, no helm value to add. If the tool reads a key, it declares it, and the admin screen shows it.

The example below is `currency_convert`. It works with no key against the ECB's free daily rates and gets intraday rates when an admin adds an Open Exchange Rates app id. That covers both patterns you will meet: a tool that degrades without a key, and a value an admin can add at run time.

---

## Step 1. Create the file

```bash
touch apps/agent-runtime/engine/tools/currency_convert.py
```

```python
"""currency_convert: ECB reference rates, or intraday rates with an Open Exchange Rates app id."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from engine.tools.base import BaseTool, ConfigField, ToolResult

_RATES_CACHE: dict[str, dict[str, float]] = {}


class CurrencyConvertTool(BaseTool):
    name = "currency_convert"
    description = (
        "Convert an amount between two currencies. Uses ECB daily reference rates, "
        "or intraday rates when Open Exchange Rates is configured. Supports 30 major currencies."
    )
    config_fields = (
        ConfigField(
            "OPENEXCHANGERATES_APP_ID",
            label="App id",
            kind="secret",
            required=False,
            group="Open Exchange Rates",
            description="Intraday rates. Without it the tool uses ECB daily reference rates.",
            signup_url="https://openexchangerates.org/signup",
        ),
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "amount": {"type": "number", "description": "Amount to convert"},
            "from_currency": {"type": "string", "description": "ISO 4217, e.g. USD"},
            "to_currency": {"type": "string", "description": "ISO 4217, e.g. EUR"},
        },
        "required": ["amount", "from_currency", "to_currency"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        amount = arguments.get("amount")
        src = (arguments.get("from_currency") or "").upper()
        dst = (arguments.get("to_currency") or "").upper()
        if not isinstance(amount, (int, float)):
            return ToolResult(content="amount must be a number", is_error=True)
        if not (len(src) == 3 and len(dst) == 3):
            return ToolResult(content="Currency codes must be 3-letter ISO 4217", is_error=True)

        warnings: list[str] = []
        app_id = self.cfg("OPENEXCHANGERATES_APP_ID")
        try:
            if app_id:
                rates, as_of, source = await self._fetch_oxr(app_id)
            else:
                rates, as_of, source = await self._fetch_ecb()
                warnings.append(
                    "OPENEXCHANGERATES_APP_ID is not configured, rates are ECB daily "
                    "reference rates, an admin can add the key under Tool Configuration"
                )
        except httpx.HTTPStatusError as e:
            if app_id and e.response.status_code in (401, 403):
                return ToolResult(
                    content="Open Exchange Rates rejected OPENEXCHANGERATES_APP_ID. "
                    "An admin can update it under Admin -> Tool Configuration.",
                    is_error=True,
                    metadata={"needs_configuration": "OPENEXCHANGERATES_APP_ID"},
                )
            return ToolResult(content=f"Rates unavailable: HTTP {e.response.status_code}", is_error=True)
        except Exception as e:  # noqa: BLE001
            return ToolResult(content=f"Rates unavailable: {e}", is_error=True)

        if src not in rates or dst not in rates:
            return ToolResult(content=f"Unsupported currency. Available: {sorted(rates)}", is_error=True)

        result = amount / rates[src] * rates[dst]
        return ToolResult(
            content=f"{amount:,.2f} {src} = {result:,.2f} {dst} ({source}, {as_of})",
            metadata={
                "amount": amount, "from": src, "to": dst, "result": result,
                "rate": rates[dst] / rates[src], "as_of": as_of, "source": source,
                "warnings": warnings,
            },
        )

    @classmethod
    async def config_test(cls, values: dict[str, str], key: str | None = None) -> tuple[bool, str] | None:
        from engine.tools._config_probe import probe

        return await probe(
            "GET", "https://openexchangerates.org/api/latest.json",
            params={"app_id": values.get("OPENEXCHANGERATES_APP_ID", ""), "symbols": "EUR"},
            accepted="Open Exchange Rates accepted the app id",
        )

    async def _fetch_ecb(self) -> tuple[dict[str, float], str, str]:
        today = datetime.now(timezone.utc).date().isoformat()
        if today in _RATES_CACHE:
            return _RATES_CACHE[today], today, "ECB reference rates"
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get("https://api.frankfurter.app/latest?from=EUR")
            r.raise_for_status()
            data = r.json()
        rates = {"EUR": 1.0, **{k: float(v) for k, v in data["rates"].items()}}
        _RATES_CACHE[today] = rates
        return rates, data["date"], "ECB reference rates"

    async def _fetch_oxr(self, app_id: str) -> tuple[dict[str, float], str, str]:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                "https://openexchangerates.org/api/latest.json",
                params={"app_id": app_id, "base": "USD"},
            )
            r.raise_for_status()
            data = r.json()
        usd = {k: float(v) for k, v in data["rates"].items()}
        rates = {k: v / usd["EUR"] for k, v in usd.items()}  # rebase to EUR
        as_of = datetime.fromtimestamp(data["timestamp"], tz=timezone.utc).isoformat(timespec="minutes")
        return rates, as_of, "Open Exchange Rates"


__all__ = ["CurrencyConvertTool"]
```

The parts that matter:

- **`config_fields`** is the whole of the tool's configuration contract. `kind` is one of `secret`, `string`, `url`, `int`, `bool`, `select`. `group` is the provider name the admin screen groups by, so two tools that read the same key end up in one card. `required=True` means the tool cannot run without it, and only single-provider tools should say so.
- **`self.cfg(KEY)`** is how you read a value. Never `os.environ`. The resolver checks, in order, a value an admin saved, the process environment, `packages/db/seeds/tool_defaults.yaml`, then the declared default. `self.cfg(KEY, required=True)` raises when nothing provides it, and the base class turns that into one standard answer for every tool: *"KEY is not configured. An admin can add it under Admin -> Tool Configuration. Get a key at <url>"*.
- **`warnings`** in the metadata reach the model. When a tool skips a source or runs in a degraded mode, say so there. The model will tell the user instead of inventing a reason.
- **`config_test`** is optional. When present, the admin screen shows a Test button that calls it with the saved values plus whatever the admin has typed. It runs in the API pod, so keep it to one cheap request.

---

## Step 2. Register it

Edit `apps/agent-runtime/engine/tools/__init__.py`:

```python
from .currency_convert import CurrencyConvertTool

ToolRegistry.register(CurrencyConvertTool)
```

The registry rejects duplicates at startup. If you forget this step the lint in step 4 tells you, because a `BaseTool` subclass that is not reachable from the registry fails the build.

---

## Step 3. Try it in isolation

```bash
cd apps/agent-runtime
python -c "
import asyncio
from engine import credentials
from engine.tools.currency_convert import CurrencyConvertTool
async def go():
    t = CurrencyConvertTool()
    r = await t.execute({'amount': 100, 'from_currency': 'USD', 'to_currency': 'EUR'})
    print(r.content)
    print(r.metadata['warnings'])
    with credentials.override({'OPENEXCHANGERATES_APP_ID': 'bad'}):
        r = await t.execute({'amount': 100, 'from_currency': 'USD', 'to_currency': 'EUR'})
        print(r.is_error, r.content)
asyncio.run(go())
"
```

Expected, in order: a conversion, a one-line warning naming the key, and the standard rejected-key error. `credentials.override` is the test seam. It wins over every other source inside the `with` block.

---

## Step 4. Run the lint

```bash
python scripts/check-tool-config.py
```

It parses every file under `engine/tools/` and fails when

- `os.environ` or `os.getenv` appears in a tool, unless the name is infrastructure (`DATABASE_URL`, `REDIS_URL` and the like),
- a key is read with `cfg()` or `credentials.get()` but no tool declares it,
- a declared key is never read and is not marked `dynamic=True`,
- a `BaseTool` subclass is not reachable from the registry.

CI runs it, `deploy.sh` runs it before building images, and `tests/unit/test_tool_contract.py` runs it under pytest. This is what makes the guarantee hold: a tool that passes CI is on the admin screen.

Then regenerate the builder's tool docs. CI runs the same script with `--check` and fails when the file is stale.

```bash
python scripts/gen-tool-docs.py --write
```

---

## Step 5. See it on the admin screen

Nothing to write. Deploy, or restart the API locally, then open **Admin -> Tool Configuration**. There is a card called Open Exchange Rates with one row, `OPENEXCHANGERATES_APP_ID`, marked optional, "not set", with "used by currency_convert" and a link to the signup page. Paste a value and Save. The row now reads "saved here". Agents use it within 30 seconds, no redeploy. Clear it and the environment or the defaults file applies again.

The same declaration shows up as a badge on `/tools`, in the builder palette, and in the agent panel's setup checklist. The Integrations page lists it under Tool credentials.

---

## Step 6. Wire it to an agent

Add the slug to an agent yaml's `model_config.tools`:

```yaml
# packages/db/seeds/agents/finance_translator.yaml
name: "Finance Translator"
slug: finance-translator
system_prompt: |
  You convert financial figures between currencies. Always use the currency_convert tool.
  Never compute conversions yourself.
model_config:
  model: claude-haiku-4-5-20251001
  tools:
    - current_time
    - currency_convert
```

If the tool has a `required=True` field, the seed must also carry it, or the seed lint fails:

```yaml
requires_credentials:
  - OPENEXCHANGERATES_APP_ID
```

Re-seed:

```bash
kubectl exec deploy/abenix-api -- python /app/packages/db/seeds/seed_agents.py
```

The deploy prints, after seeding, which seeded agents need credentials that are not set.

---

## Step 7. Try it via the UI

Open `/agents`, pick finance-translator, Test. Ask

```
Convert 1000 USD to JPY.
```

The trace shows the tool call, the result, and under it the tool note about ECB rates when no app id is set. The Flight Recorder at `/executions/<id>` keeps the result and the duration.

---

## Step 8. Unit test

`apps/agent-runtime/tests/tools/test_currency_convert.py`:

```python
import pytest
from engine import credentials
from engine.tools.currency_convert import CurrencyConvertTool


@pytest.mark.asyncio
async def test_ecb_path_warns_about_the_missing_key(monkeypatch):
    async def fake_ecb(self):
        return {"EUR": 1.0, "USD": 1.08}, "2026-05-20", "ECB reference rates"
    monkeypatch.setattr(CurrencyConvertTool, "_fetch_ecb", fake_ecb)
    with credentials.override({"OPENEXCHANGERATES_APP_ID": ""}):
        r = await CurrencyConvertTool().execute({"amount": 100, "from_currency": "EUR", "to_currency": "USD"})
    assert not r.is_error
    assert "108.00 USD" in r.content
    assert r.metadata["warnings"]


@pytest.mark.asyncio
async def test_key_is_used_when_present(monkeypatch):
    seen = {}
    async def fake_oxr(self, app_id):
        seen["app_id"] = app_id
        return {"EUR": 1.0, "USD": 1.08}, "2026-05-20T10:00+00:00", "Open Exchange Rates"
    monkeypatch.setattr(CurrencyConvertTool, "_fetch_oxr", fake_oxr)
    with credentials.override({"OPENEXCHANGERATES_APP_ID": "abc"}):
        r = await CurrencyConvertTool().execute({"amount": 100, "from_currency": "EUR", "to_currency": "USD"})
    assert seen["app_id"] == "abc"
    assert r.metadata["warnings"] == []


def test_declaration_reaches_the_admin_catalogue():
    from app.services import tool_config
    tool_config.reset_cache()
    decl = tool_config.declarations()["OPENEXCHANGERATES_APP_ID"]
    assert "currency_convert" in decl.tools
    assert decl.group == "Open Exchange Rates"
```

Run `pytest tests/tools/test_currency_convert.py -v`. The last test needs `apps/api` on the path, which `tests/unit/conftest.py` sets up.

---

## Step 9. Deploy

```bash
bash scripts/deploy.sh local          # minikube
bash scripts/deploy-azure.sh redeploy # AKS, always the full redeploy
```

Both run the lint first and refuse to build when it fails.

---

## Common patterns

### A key several tools share

Declare it in each tool with the same `group`. Storage is per key, so the admin enters it once and every declaring tool lists under "used by". `OPENAI_API_KEY` is declared by eight tools and the three LLM nodes this way.

### A table-driven tool

Generate the fields from the table so they cannot drift:

```python
_PROVIDERS = [("tavily", "TAVILY_API_KEY", "https://api.tavily.com/search"), ...]

class TavilySearchTool(BaseTool):
    config_fields = tuple(
        ConfigField(env, label=f"{prov.title()} API key", kind="secret", group=prov.title(), dynamic=True)
        for prov, env, _url in _PROVIDERS
    )
```

`dynamic=True` tells the lint the key is read under a name built at run time.

### A module-level helper with no `self`

```python
from engine import credentials

def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers={"Authorization": f"Bearer {credentials.get('GITHUB_TOKEN')}"})
```

### Infrastructure values

`DATABASE_URL`, `REDIS_URL`, broker URLs and data paths are not tool configuration and stay in the environment. The lint allows them by name. If you need one the lint does not know, add it to `INFRA_ENV` in `scripts/check-tool-config.py` with a one-line reason.

### Reading from Postgres

```python
import asyncpg

async def execute(self, arguments):
    async with asyncpg.connect(self.db_url) as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM widgets WHERE tenant_id = $1 AND status = $2",
            self.tenant_id, arguments["status"],
        )
    return ToolResult(content=str(count))
```

---

## Don't forget

- **`tenant_id` filter on every DB query.** The base class gives you `self.tenant_id`.
- **Timeouts on external calls.** 60s is the runtime cap. Keep HTTP timeouts at 10 to 20s.
- **Idempotency** if the tool mutates state. The agent may call it twice.
- **A rejected key is an error, not an empty result.** Return `is_error=True` with `metadata.needs_configuration` naming the key, as above.
- **Degraded modes go in `warnings`.** Skipped sources go in `sources_skipped`. The model sees both.
- **No `os.environ` in a tool.** The lint will tell you, but it is quicker to not write it.

---

## See also

- [08-tool-configuration](08-tool-configuration.md), how the configuration mechanism works end to end, for admins and operators
- [02-runtime/02-tools](../02-runtime/02-tools.md), the framework reference
- [02-add-an-agent](02-add-an-agent.md), give the tool somewhere to be used
- [09-reference/04-platform-settings](../09-reference/04-platform-settings.md), where saved values live

---

## Source map

| What | Where |
|---|---|
| **Tool base class** | [`apps/agent-runtime/engine/tools/base.py`](../../apps/agent-runtime/engine/tools/base.py), `BaseTool`, `ConfigField`, `ToolResult`, `ToolNeedsConfiguration` |
| **Credential resolver** | [`apps/agent-runtime/engine/credentials.py`](../../apps/agent-runtime/engine/credentials.py), precedence, TTL, `override()` |
| **Key test helper** | [`apps/agent-runtime/engine/tools/_config_probe.py`](../../apps/agent-runtime/engine/tools/_config_probe.py) |
| **The lint** | [`scripts/check-tool-config.py`](../../scripts/check-tool-config.py), run by CI, `deploy.sh` and `tests/unit/test_tool_contract.py` |
| **Catalogue the admin screen is built from** | [`apps/api/app/services/tool_config.py`](../../apps/api/app/services/tool_config.py) |
| **Admin endpoints** | [`apps/api/app/routers/admin_tool_config.py`](../../apps/api/app/routers/admin_tool_config.py), `/api/admin/tool-config` |
| **Admin screen** | [`apps/web/src/app/(app)/admin/tool-config/page.tsx`](../../apps/web/src/app/(app)/admin/tool-config/page.tsx) |
| **Tool registry** | [`apps/agent-runtime/engine/tools/__init__.py`](../../apps/agent-runtime/engine/tools/__init__.py) |
| **Existing tools** | [`apps/agent-runtime/engine/tools/`](../../apps/agent-runtime/engine/tools/), copy the closest one |
| **Tool gate (cache + semaphore + qps + breaker)** | [`apps/api/app/core/tool_gate.py`](../../apps/api/app/core/tool_gate.py) |
| **Per-tool runtime config (admin UI knobs)** | [`packages/db/models/tool_runtime_config.py`](../../packages/db/models/tool_runtime_config.py), surfaced at `/admin/tool-scaling` |
| **Connectors framework (for systems with auth)** | [`apps/agent-runtime/engine/tools/_connector_base.py`](../../apps/agent-runtime/engine/tools/) + [14-connectors-and-triggers](../02-runtime/14-connectors-and-triggers.md) |
