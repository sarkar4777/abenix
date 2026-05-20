# How to add a new tool

> A complete walkthrough — from the empty file to a tool an agent can call. Takes ~30 minutes including tests.

---

## The example we'll build

A `currency_convert` tool that converts an amount between two currencies using the European Central Bank's free reference rates. Pure-Python, no LLM, demonstrates every part of the framework.

---

## Step 1 — Create the file

```bash
touch apps/agent-runtime/engine/tools/currency_convert.py
```

```python
"""currency_convert — ECB reference-rate currency conversion."""

from datetime import datetime, timezone
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

# Reference cache keyed by date — ECB updates once per day.
_RATES_CACHE: dict[str, dict[str, float]] = {}


class CurrencyConvertTool(BaseTool):
    name = "currency_convert"
    description = (
        "Convert an amount between two currencies using ECB daily reference rates. "
        "Free, public-domain, EUR-based. Supports 30 major currencies."
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
            return ToolResult(content="`amount` must be a number", is_error=True)
        if not (len(src) == 3 and len(dst) == 3):
            return ToolResult(content="Currency codes must be 3-letter ISO 4217 (e.g. USD)", is_error=True)

        try:
            rates, as_of = await self._fetch_rates()
        except Exception as e:
            return ToolResult(content=f"ECB rates unavailable: {e}", is_error=True)

        if src not in rates or dst not in rates:
            return ToolResult(
                content=f"Unsupported currency. Available: {sorted(rates)}",
                is_error=True,
            )

        eur_amount = amount / rates[src]
        result = eur_amount * rates[dst]
        return ToolResult(
            content=f"{amount:,.2f} {src} = {result:,.2f} {dst}",
            metadata={
                "amount": amount,
                "from": src,
                "to": dst,
                "result": result,
                "rate": rates[dst] / rates[src],
                "as_of": as_of,
                "source": "ECB reference rates",
            },
        )

    async def _fetch_rates(self) -> tuple[dict[str, float], str]:
        today = datetime.now(timezone.utc).date().isoformat()
        if today in _RATES_CACHE:
            return _RATES_CACHE[today], today
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get("https://api.frankfurter.app/latest?from=EUR")
            r.raise_for_status()
            data = r.json()
        rates = {"EUR": 1.0, **{k: float(v) for k, v in data["rates"].items()}}
        _RATES_CACHE[today] = rates
        return rates, data["date"]


__all__ = ["CurrencyConvertTool"]
```

---

## Step 2 — Register it

Edit `apps/agent-runtime/engine/tools/__init__.py`:

```python
from .currency_convert import CurrencyConvertTool

ToolRegistry.register(CurrencyConvertTool)
```

The registry rejects duplicates at startup. If you forget, the agent gets `KeyError: Tool 'currency_convert' not registered` on first dispatch.

---

## Step 3 — Test in isolation

```bash
cd apps/agent-runtime
python -c "
import asyncio
from engine.tools.currency_convert import CurrencyConvertTool
async def go():
    t = CurrencyConvertTool()
    r = await t.execute({'amount': 100, 'from_currency': 'USD', 'to_currency': 'EUR'})
    print(r.content)
    print(r.metadata)
asyncio.run(go())
"
```

Expected: `100.00 USD = 92.34 EUR` and the metadata dict.

---

## Step 4 — Wire it to an agent

Pick or create an agent yaml that should be able to call your tool. Add the slug to `model_config.tools`:

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

Re-seed agents:
```bash
kubectl exec deploy/abenix-api -- python /app/packages/db/seeds/seed_agents.py
```

---

## Step 5 — Try it via the UI

Visit `/agents → finance-translator → Test`. Submit:

```
Convert 1000 USD to JPY.
```

You should see the tool call in the trace + the final answer.

---

## Step 6 — Add a unit test

`apps/agent-runtime/tests/tools/test_currency_convert.py`:

```python
import pytest
from engine.tools.currency_convert import CurrencyConvertTool


@pytest.mark.asyncio
async def test_eur_to_usd_with_mock(monkeypatch):
    async def fake_fetch(_):
        return {"EUR": 1.0, "USD": 1.08}, "2026-05-20"
    monkeypatch.setattr(CurrencyConvertTool, "_fetch_rates", fake_fetch)

    t = CurrencyConvertTool()
    r = await t.execute({"amount": 100, "from_currency": "EUR", "to_currency": "USD"})
    assert not r.is_error
    assert "108.00 USD" in r.content
    assert r.metadata["rate"] == pytest.approx(1.08)


@pytest.mark.asyncio
async def test_invalid_currency():
    t = CurrencyConvertTool()
    r = await t.execute({"amount": 100, "from_currency": "XYZ", "to_currency": "EUR"})
    assert r.is_error
```

Run: `pytest tests/tools/test_currency_convert.py -v`.

---

## Step 7 — (Optional) Deploy

```bash
bash scripts/deploy-azure.sh redeploy --only=agent-runtime
```

The new tool is registered when the runtime pods restart.

---

## Common patterns

### Reading from Postgres
```python
import asyncpg

class WidgetCountTool(BaseTool):
    name = "widget_count"
    ...
    async def execute(self, arguments):
        async with asyncpg.connect(self.db_url) as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM widgets WHERE tenant_id = $1 AND status = $2",
                self.tenant_id, arguments["status"],
            )
        return ToolResult(content=str(count))
```

### Calling another agent
```python
from abenix_sdk import Abenix

class SubAgentTool(BaseTool):
    name = "invoke_sub_agent"
    ...
    async def execute(self, arguments):
        async with Abenix(...) as client:
            result = await client.execute(arguments["slug"], arguments["input"], wait="complete")
        return ToolResult(content=str(result.output))
```

### Writing files to S3
```python
class ExportTool(BaseTool):
    name = "export_report"
    ...
    async def execute(self, arguments):
        key = f"reports/{self.tenant_id}/{uuid.uuid4().hex}.csv"
        await blob.upload(key, csv_bytes)
        return ToolResult(content=f"Report at {key}", output_files=[key])
```

---

## Don't forget

- **`tenant_id` filter on every DB query**. The base class gives you `self.tenant_id` — use it.
- **Timeout on external calls**. 60s is the runtime cap. your tool's HTTP timeout should be 10-20s.
- **Idempotency** if your tool mutates state. The agent may call it twice.
- **Set sensible `metadata`** — it shows in the trace and is queryable.
- **Add it to the `/help` page** if it's user-facing.

---

## See also

- [02-runtime/02-tools](../02-runtime/02-tools.md) — framework reference
- [02-add-an-agent](02-add-an-agent.md) — give the tool somewhere to be used
