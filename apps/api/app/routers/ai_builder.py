"""AI Builder — Generate agent/pipeline configs from natural language descriptions."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.core.config import settings
from app.core.platform_settings import get_setting as _get_setting

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))

from models.user import User

router = APIRouter(prefix="/api/ai", tags=["ai-builder"])


def _load_tool_catalog() -> list[tuple[str, str]]:
    """Dynamically load tool descriptions from all tool classes."""
    import importlib
    import os

    tools_dir = (
        Path(__file__).resolve().parents[4]
        / "apps"
        / "agent-runtime"
        / "engine"
        / "tools"
    )
    skip = {"__init__", "base", "pipeline_tool"}
    catalog: list[tuple[str, str]] = []

    for f in sorted(os.listdir(tools_dir)):
        if not f.endswith(".py") or f.replace(".py", "") in skip:
            continue
        try:
            mod = importlib.import_module(f"engine.tools.{f[:-3]}")
            for attr_name in dir(mod):
                cls = getattr(mod, attr_name)
                if (
                    isinstance(cls, type)
                    and hasattr(cls, "name")
                    and hasattr(cls, "input_schema")
                    and hasattr(cls, "description")
                ):
                    name = cls.name if isinstance(cls.name, str) else ""
                    if not name:
                        continue
                    desc = cls.description if isinstance(cls.description, str) else ""
                    schema = (
                        cls.input_schema if isinstance(cls.input_schema, dict) else {}
                    )
                    props = schema.get("properties", {})
                    req = schema.get("required", [])
                    params = []
                    for pn, pi in props.items():
                        r = "required" if pn in req else "optional"
                        type_str = pi.get("type", "any")
                        # Include enum/allowed values so the AI knows exact capabilities
                        if "enum" in pi:
                            type_str = f'enum[{"|".join(str(v) for v in pi["enum"])}]'
                        param_desc = pi.get("description", "")[:120]
                        params.append(f"{pn} ({type_str}, {r}): {param_desc}")
                    param_str = "; ".join(params) if params else "none"
                    catalog.append((name, f"{desc[:300]}. Params: {param_str}"))
        except Exception:
            continue

    # SchemaPortfolioTool doesn't expose a class-level `name` (it's set at
    # instance time from the domain). Add its canonical aliases here so the
    # AI Builder can pick the right slug when the user asks for "portfolio
    # tool" / "energy contracts" / etc.
    existing = {n for n, _ in catalog}
    schema_tools = [
        (
            "portfolio_energy_contracts",
            "Schema-driven portfolio tool for PPA / gas / tolling energy contracts. "
            "Loads its schema from portfolio_schemas table at runtime. Operations: "
            "list_records, get_summary, filter_by_status, filter_by_counterparty, "
            "aggregate_exposure. Params: action (enum[list|summary|filter|aggregate], "
            "required); filters (object, optional).",
        ),
    ]
    for name, desc in schema_tools:
        if name not in existing:
            catalog.append((name, desc))

    return catalog if catalog else _FALLBACK_TOOLS


_FALLBACK_TOOLS = [
    (
        "calculator",
        "Evaluate math expressions. Input: {expression: string}. Output: numeric result.",
    ),
    (
        "web_search",
        "Search the internet. Input: {query: string, max_results?: int}. Output: search results with titles, URLs, snippets.",
    ),
    (
        "llm_call",
        "Call an LLM for text generation. Input: {prompt: string, model?: string}. Output: {response: string, tokens, cost}.",
    ),
    (
        "llm_route",
        "AI-powered classification. Input: {prompt: string, branches: string[], context?: string}. Output: {route: string, confidence: float}.",
    ),
    (
        "code_executor",
        "Run sandboxed Python code. Input: {code: string, variables?: object}. Output: stdout + result variable.",
    ),
    (
        "file_reader",
        "Read PDF, DOCX, CSV, TXT files. Input: {file_path: string}. Output: extracted text content.",
    ),
    (
        "document_extractor",
        "Extract structured data from documents. Input: {text or file_path, extract_type: tables|key_values|sections|entities|all}. Output: structured JSON.",
    ),
    (
        "csv_analyzer",
        "Analyze CSV data with statistics. Input: {file_path: string, query?: string}. Output: analysis results.",
    ),
    (
        "json_transformer",
        "Query/filter/transform JSON. Input: {input_json, operation, field_name?, field_value?}. Output: transformed JSON.",
    ),
    (
        "text_analyzer",
        "Analyze text: keywords, readability, sentiment. Input: {text: string, analyses: string[]}. Output: analysis results.",
    ),
    (
        "http_client",
        "Make HTTP API calls. Input: {url, method, headers?, body?}. Output: response body + status.",
    ),
    (
        "email_sender",
        "Send email via SMTP. Input: {to, subject, body, html?}. Output: success/failure.",
    ),
    (
        "data_merger",
        "Merge multiple data sources. Input: {sources: object[], mode: flat|nested|compare}. Output: merged data.",
    ),
    (
        "financial_calculator",
        "DCF, NPV, IRR, LCOE calculations. Input: {calculation_type, parameters}. Output: financial results.",
    ),
    (
        "risk_analyzer",
        "Monte Carlo, VaR, sensitivity analysis. Input: {analysis_type, parameters}. Output: risk metrics.",
    ),
    (
        "current_time",
        "Get current date/time in any timezone. Input: {timezone?: string}. Output: formatted datetime.",
    ),
    (
        "human_approval",
        "Pause for human approval. Input: {action, details, risk_level}. Output: approved/rejected.",
    ),
    (
        "structured_analyzer",
        "LLM-powered analysis of any content. Input: {custom_prompt, output_format?}. Output: structured JSON.",
    ),
    (
        "regex_extractor",
        "Extract patterns from text. Input: {text, patterns: object}. Output: matches.",
    ),
    (
        "database_query",
        "Query PostgreSQL. Input: {query: string, params?: object}. Output: rows.",
    ),
    (
        "github_tool",
        "Interact with GitHub repos. Input: {action, owner, repo, ...}. Output: API response.",
    ),
    (
        "time_series_analyzer",
        "Statistical analysis of time-series. Input: {data: number[], operation: statistics|anomaly_detection|forecast}. Output: analysis.",
    ),
    (
        "pii_redactor",
        "Detect/mask PII in text. Input: {text, strategy: mask|remove|detect_only}. Output: redacted text.",
    ),
    (
        "unit_converter",
        "Convert between units. Input: {value, from_unit, to_unit}. Output: converted value.",
    ),
    (
        "market_data",
        "Get stock/forex/commodity data. Input: {symbol, data_type}. Output: market data.",
    ),
]

# Lazy-loaded complete tool catalog (populated on first use)
_TOOL_CATALOG: list[tuple[str, str]] | None = None


def _get_tools() -> list[tuple[str, str]]:
    global _TOOL_CATALOG
    if _TOOL_CATALOG is None:
        try:
            _TOOL_CATALOG = _load_tool_catalog()
        except Exception:
            _TOOL_CATALOG = _FALLBACK_TOOLS
    return _TOOL_CATALOG


PIPELINE_FEATURES = """
PIPELINE NODE PROPERTIES:
- depends_on: list of node IDs this node depends on (runs after them)
- condition: {{source_node, field, operator (eq/neq/gt/lt/gte/lte/contains), value}} — skip node if condition not met
- switch config: {{source_node, field, cases: [{{operator, value, target_node}}], default_node}} — multi-branch routing
- merge config: {{mode: append|zip|join, source_nodes: [...]}} — combine branch outputs
- on_error: "stop" | "continue" | "error_branch" — error handling
- error_branch_node: node ID to activate on failure
- timeout_seconds: per-node timeout (1-300)
- for_each: {{source_node, source_field, item_variable, max_concurrency}} — parallel iteration
- Template variables: {{{{node_id.field}}}} or {{{{node_id.__all__}}}} in string arguments reference upstream node outputs
Built-in nodes: __switch__ (routing), __merge__ (combining), wait (delay), state_get/state_set (persistence)

DATA FLOW BETWEEN NODES:
- Every tool returns a JSON object. Downstream nodes reference fields via {{{{node_id.field_name}}}}
- {{{{node_id.__all__}}}} passes the entire output as a string
- code_executor nodes automatically receive all upstream outputs in a `context` dict (e.g. context["read_pdf"])

FILE GENERATION PATTERNS (IMPORTANT):
When the user needs file output (Excel, PDF, reports, exports), use these patterns:

Pattern 1 — data_exporter with format:
  Use data_exporter for straightforward data-to-file export. It natively supports:
  json, csv, txt, markdown, html, xlsx (Excel with formatting), pdf (report)
  Example: {{"tool_name": "data_exporter", "arguments": {{"destination": "file", "data": "{{{{analyze.__all__}}}}", "format": "xlsx", "filename": "report.xlsx"}}}}

Pattern 2 — code_executor for complex file generation:
  Use code_executor when you need custom formatting, charts, multi-sheet Excel, or complex layouts.
  code_executor can save files via save_export(filename, bytes) or open(filename, 'wb').
  Libraries available: openpyxl (Excel), pandas, numpy, json, csv, io, base64.
  Example: {{"tool_name": "code_executor", "arguments": {{"code": "import openpyxl\\nimport json\\n\\ndata = json.loads(context['analyze']['response'])\\nwb = openpyxl.Workbook()\\nws = wb.active\\nws.title = 'Results'\\nfor i, row in enumerate(data):\\n    for j, (k,v) in enumerate(row.items()):\\n        if i == 0: ws.cell(1, j+1, value=k)\\n        ws.cell(i+2, j+1, value=v)\\nimport io\\nbuf = io.BytesIO()\\nwb.save(buf)\\npath = save_export('report.xlsx', buf.getvalue())\\nresult = {{'file_path': path, 'status': 'success'}}"}}}}

Pattern 3 — llm_call + code_executor chain:
  For tasks that need AI analysis THEN file generation:
  Step 1: llm_call with a prompt that asks the LLM to return structured JSON
  Step 2: code_executor that takes the LLM output and generates the file
  This is useful for: AI-written reports → PDF, AI analysis → formatted Excel, etc.

LLM_CALL NODE RULES:
- EVERY llm_call node MUST have a non-empty "prompt" argument. Never leave it empty.
- The prompt should describe exactly what output you need from the LLM.
- Use template variables to inject upstream data: "Analyze this data: {{{{read_pdf.__all__}}}}"
- Include a system_prompt when the LLM needs specific behavior (e.g., "Return valid JSON only")
- For structured output, instruct the LLM in the prompt: "Return a JSON array of objects with keys: name, value, category"

EXAMPLE PIPELINE (PDF analysis → Excel report):
  Node 1: {{"id": "read_pdf", "tool_name": "file_reader", "arguments": {{"file_path": "{{{{context.file_url}}}}"}}, "depends_on": []}}
  Node 2: {{"id": "analyze", "tool_name": "llm_call", "arguments": {{"prompt": "Analyze this document and extract all key data points as a JSON array of objects with keys: section, finding, value, importance (high/medium/low):\\n\\n{{{{read_pdf.__all__}}}}", "system_prompt": "You are a document analyst. Always return valid JSON arrays.", "model": "claude-sonnet-4-5-20250929"}}, "depends_on": ["read_pdf"]}}
  Node 3: {{"id": "create_report", "tool_name": "data_exporter", "arguments": {{"destination": "file", "data": "{{{{analyze.response}}}}", "format": "xlsx", "filename": "analysis_report.xlsx"}}, "depends_on": ["analyze"]}}
  Node 4: {{"id": "send_email", "tool_name": "email_sender", "arguments": {{"to": "{{{{context.email}}}}", "subject": "Analysis Report Ready", "body": "Your report is attached: {{{{create_report.file_path}}}}"}}, "depends_on": ["create_report"]}}

EXAMPLE PIPELINE (parallel branches fan-in via data_merger):
  Node 1: {{"id": "fetch_prices", "tool_name": "http_client", "arguments": {{"url": "{{{{context.price_api_url}}}}", "method": "GET"}}, "depends_on": []}}
  Node 2: {{"id": "trends", "tool_name": "time_series_analyzer", "arguments": {{"data": "{{{{fetch_prices.response.prices}}}}", "operation": "statistics"}}, "depends_on": ["fetch_prices"]}}
  Node 3: {{"id": "forecast", "tool_name": "time_series_analyzer", "arguments": {{"data": "{{{{fetch_prices.response.prices}}}}", "operation": "forecast"}}, "depends_on": ["fetch_prices"]}}
  Node 4: {{"id": "combine", "tool_name": "data_merger", "arguments": {{"sources": ["{{{{trends.response}}}}", "{{{{forecast.response}}}}"], "mode": "flat"}}, "depends_on": ["trends", "forecast"]}}
  Node 5: {{"id": "report", "tool_name": "llm_call", "arguments": {{"prompt": "Summarize: {{{{combine.response}}}}"}}, "depends_on": ["combine"]}}
  NOTE: without the `combine` node, `report` only receives `trends`'s output — `forecast` is silently lost. ALWAYS insert a data_merger (or __merge__) whenever 2+ nodes fan in to one node.
"""


async def _get_mcp_registry(db: Any = None) -> str:
    """Dynamically load MCP registry from database (not hardcoded)."""
    try:
        if db:
            from models.mcp_connection import MCPRegistryCache

            result = await db.execute(select(MCPRegistryCache))
            entries = result.scalars().all()
            if entries:
                lines = ["AVAILABLE MCP INTEGRATIONS (external service connectors):"]
                for e in entries:
                    lines.append(
                        f"- {e.registry_id}: {e.name} — {e.description} ({e.tools_count} tools, {e.auth_type})"
                    )
                lines.append(
                    "\nIf the user's request involves a third-party service, suggest relevant MCP servers."
                )
                return "\n".join(lines)
    except Exception:
        pass
    # Fallback if DB unavailable
    return """AVAILABLE MCP INTEGRATIONS: github-mcp, slack-mcp, postgres-mcp, stripe-mcp, notion-mcp, jira-mcp, google-drive-mcp, weather-mcp
If the user's request involves a third-party service, suggest relevant MCP servers."""


async def _get_existing_agents_context(db: Any, tenant_id: str) -> str:
    """Load existing agent/pipeline configs so the AI builder can reference them."""
    try:
        from models.agent import Agent, AgentType
        from sqlalchemy import or_ as sql_or

        # Include OOB agents (shared across tenants) alongside this tenant's own.
        result = await db.execute(
            select(Agent)
            .where(
                sql_or(Agent.tenant_id == tenant_id, Agent.agent_type == AgentType.OOB),
            )
            .limit(30)
        )
        agents = result.scalars().all()
        if not agents:
            return ""
        lines = [
            "EXISTING AGENTS/PIPELINES IN YOUR WORKSPACE (you can reference these patterns — use same tool names, same template style):"
        ]
        for a in agents:
            cfg = a.model_config_ or {}
            mode = cfg.get("mode", "agent")
            tools = cfg.get("tools") or []
            tools_str = ", ".join(tools[:8]) if tools else "none"
            pipeline_cfg = cfg.get("pipeline_config") or {}
            nodes = pipeline_cfg.get("nodes") or []
            line = f"- {a.name} ({mode}): {(a.description or '')[:120]}"
            if mode == "pipeline":
                line += f" | {len(nodes)} nodes | tools: {tools_str}"
            else:
                line += f" | tools: {tools_str}"
            lines.append(line)
        return "\n".join(lines)
    except Exception:
        return ""


async def _get_code_assets_context(db: Any, tenant_id: str) -> str:
    """List the tenant's ready code assets so the AI builder can pick them"""
    try:
        from models.code_asset import CodeAsset, CodeAssetStatus

        result = await db.execute(
            select(CodeAsset)
            .where(
                CodeAsset.tenant_id == tenant_id,
                CodeAsset.status == CodeAssetStatus.READY,
            )
            .order_by(CodeAsset.created_at.desc())
            .limit(30)
        )
        assets = result.scalars().all()
        if not assets:
            return ""
        lines = [
            "CODE ASSETS UPLOADED BY THE USER (callable via the `code_asset` tool):",
            "When the user references one of these by name, purpose, or language, "
            "use its UUID as the `code_asset_id` argument. Example call:",
            '    code_asset(code_asset_id="<uuid>", input={...})',
            "",
        ]
        for a in assets:
            lang = a.detected_language or "unknown"
            ver = a.detected_version or ""
            entry = a.detected_entrypoint or "?"
            desc = (a.description or "").strip()[:180]
            in_schema = ""
            out_schema = ""
            if a.input_schema:
                # Summarize the shape — not dump the whole schema which
                # inflates the prompt. Top-level properties + required.
                props = list((a.input_schema.get("properties") or {}).keys())[:8]
                req = a.input_schema.get("required") or []
                in_schema = f" input={{keys: {props}, required: {req}}}"
            if a.output_schema:
                props = list((a.output_schema.get("properties") or {}).keys())[:8]
                out_schema = f" output={{keys: {props}}}"
            lines.append(
                f"- \"{a.name}\" (id: {a.id}) — {desc or '(no description)'}. "
                f"Lang: {lang} {ver}, entry: {entry}.{in_schema}{out_schema}"
            )
        lines.append("")
        lines.append(
            'When a user says things like "my Go preprocessor", "the Java tokenizer", '
            'or "use my summarizer step", match by name/language/description above '
            'and emit `code_asset_id="<that uuid>"` in the generated system prompt.'
        )
        return "\n".join(lines)
    except Exception:
        return ""


async def _get_pipeline_examples_context() -> str:
    """Load sample pipeline YAML patterns for reference."""
    try:
        seeds_dir = (
            Path(__file__).resolve().parents[4] / "packages" / "db" / "seeds" / "agents"
        )
        if not seeds_dir.exists():
            return ""

        import yaml

        lines = [
            "REFERENCE PIPELINE PATTERNS (from seed agents — mimic these exactly for tool names, template syntax, depends_on wiring):"
        ]
        count = 0
        expanded_shown = False
        for f in sorted(seeds_dir.glob("*.yaml")):
            if count >= 6:
                break
            try:
                with open(f, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                if not data or data.get("mode") != "pipeline":
                    continue
                nodes = data.get("pipeline_config", {}).get("nodes", [])
                node_summary = " → ".join(
                    f'{n["id"]}({n.get("tool_name", "?")})' for n in nodes[:8]
                )
                if len(nodes) > 8:
                    node_summary += f" ... +{len(nodes) - 8} more"
                tools_used = sorted(
                    {n.get("tool_name", "") for n in nodes if n.get("tool_name")}
                )
                input_vars = [
                    v.get("name")
                    for v in (data.get("input_variables") or [])
                    if isinstance(v, dict)
                ]
                lines.append(
                    f"- {data.get('name', f.stem)} ({len(nodes)} nodes): {node_summary}"
                )
                lines.append(
                    f"  Tools: {', '.join(tools_used)}  |  Input vars: {', '.join(input_vars) or 'none'}"
                )
                # Expand the FIRST example fully so the AI sees real arguments.
                if not expanded_shown and nodes:
                    import json as _json

                    sample_nodes = []
                    for n in nodes[:3]:
                        simple = {
                            "id": n.get("id"),
                            "tool_name": n.get("tool_name"),
                            "arguments": n.get("arguments", {}),
                            "depends_on": n.get("depends_on", []),
                        }
                        sample_nodes.append(simple)
                    lines.append(
                        f"  Sample (first 3 nodes, verbatim): {_json.dumps(sample_nodes)[:1500]}"
                    )
                    expanded_shown = True
                count += 1
            except Exception:
                continue
        return "\n".join(lines) if count > 0 else ""
    except Exception:
        return ""


async def _get_sandbox_policy(tenant_id: str) -> dict[str, Any]:
    """Resolve effective sandbox settings for a tenant: Redis override ∪ env."""
    import os as _os

    env_enabled = _os.environ.get("SANDBOXED_JOB_ENABLED", "").lower() in (
        "1",
        "true",
        "yes",
    )
    env_network = _os.environ.get("SANDBOXED_JOB_ALLOW_NETWORK", "").lower() in (
        "1",
        "true",
        "yes",
    )
    env_images = sorted(
        {
            i.strip()
            for i in _os.environ.get("SANDBOXED_JOB_ALLOWED_IMAGES", "").split(",")
            if i.strip()
        }
    )
    enabled, allow_net, images = env_enabled, env_network, env_images
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(str(settings.redis_url), decode_responses=True)
        raw = await r.hgetall(f"sandbox:settings:{tenant_id}")
        await r.aclose()
        if raw:
            if "enabled" in raw:
                enabled = raw["enabled"].strip().lower() in ("1", "true", "yes")
            if "allow_network" in raw:
                allow_net = raw["allow_network"].strip().lower() in ("1", "true", "yes")
            if "allowed_images" in raw and raw["allowed_images"].strip():
                images = sorted(
                    {i.strip() for i in raw["allowed_images"].split(",") if i.strip()}
                )
    except Exception:
        pass
    return {"enabled": enabled, "allow_network": allow_net, "allowed_images": images}


async def _get_sandbox_policy_context(tenant_id: str) -> str:
    """Prompt section declaring which sandbox features this tenant can use."""
    p = await _get_sandbox_policy(tenant_id)
    if not p["enabled"]:
        return (
            "╔══════════════════════════════════════════════════════════════╗\n"
            "║  SANDBOX POLICY — DISABLED FOR THIS TENANT                   ║\n"
            "╠══════════════════════════════════════════════════════════════╣\n"
            "║  • DO NOT USE `sandboxed_job` — it is not in the tool catalog║\n"
            "║    below and calls to it will be rejected at runtime.        ║\n"
            "║  • If a step needs a binary that Python stdlib can't provide,║\n"
            "║    propose a `custom_tool` in the `custom_tools` array       ║\n"
            "║    describing the behaviour. The platform will synthesise it.║\n"
            "║  • Otherwise prefer `code_executor` for in-process Python.   ║\n"
            "╚══════════════════════════════════════════════════════════════╝\n"
        )
    img_line = (
        ", ".join(p["allowed_images"])
        if p["allowed_images"]
        else "(none — sandboxed_job will reject every call)"
    )
    net_line = (
        "ON — pipeline nodes may set `network: true`"
        if p["allow_network"]
        else "OFF — do NOT set network:true on any sandboxed_job node; jobs are isolated from the internet"
    )
    return (
        "SANDBOX POLICY FOR THIS TENANT:\n"
        f"  • sandboxed_job is enabled.\n"
        f"  • Allowed images (reject any other): {img_line}\n"
        f"  • Network policy: {net_line}\n"
        "  • If the task needs an image not on this list, propose a custom_tool instead of "
        "picking a random image — the runtime will reject it.\n"
    )


async def _get_tools_filtered(tenant_id: str) -> list[tuple[str, str]]:
    """Same as _get_tools() but drops tools the tenant has disabled by policy."""
    policy = await _get_sandbox_policy(tenant_id)
    catalog = _get_tools()
    if policy["enabled"]:
        return catalog
    return [(name, desc) for (name, desc) in catalog if name != "sandboxed_job"]


async def _get_saved_tools_context(db: Any, tenant_id: str) -> str:
    """Load approved custom tools from the tool library (not hardcoded)."""
    try:
        from models.saved_tool import SavedTool

        result = await db.execute(
            select(SavedTool).where(
                SavedTool.tenant_id == tenant_id,
                SavedTool.status == "approved",
            )
        )
        tools = result.scalars().all()
        if tools:
            lines = ["CUSTOM TOOLS (admin-approved, available in your workspace):"]
            for t in tools:
                perms = t.permissions or {}
                perm_str = ""
                if perms.get("network"):
                    perm_str = " [has network access]"
                lines.append(f"- {t.name}: {t.description}{perm_str}")
            return "\n".join(lines)
    except Exception:
        pass
    return ""


def _parse_builder_json(text: str, stop_reason: str | None = None) -> dict[str, Any]:
    """Robustly extract a JSON config from an LLM response."""
    s = text.strip()
    # Strip leading markdown fence if present.
    if s.startswith("```"):
        s = s.lstrip("`")
        # Drop optional "json" language tag on the first line.
        first_nl = s.find("\n")
        if first_nl != -1 and s[:first_nl].strip().lower() in {"json", ""}:
            s = s[first_nl + 1 :]
        # Strip trailing fence if any.
        if s.rstrip().endswith("```"):
            s = s.rstrip().rstrip("`")
    if "{" not in s:
        raise ValueError("LLM did not return JSON — response was all prose.")
    s = s[s.index("{") : s.rindex("}") + 1]
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        truncated = stop_reason == "max_tokens" or "Unterminated" in str(e)
        if truncated:
            raise ValueError(
                "The AI generated a config too large to fit in one response "
                f"(~{len(text):,} chars) and got cut off. "
                "Try again with a more focused description, or enable "
                "'Iterative (validate + judge)' mode — it regenerates on failure."
            ) from e
        # Show a short excerpt around the error so the cause is visible.
        excerpt = s[max(0, e.pos - 60) : e.pos + 60].replace("\n", " ")
        raise ValueError(
            f"Failed to parse AI response as JSON at char {e.pos}: {e.msg}. "
            f"Near: …{excerpt}…"
        ) from e


class BuildAgentRequest(BaseModel):
    description: str = Field(..., min_length=10, max_length=5000)
    mode: str = Field(default="auto", pattern="^(agent|pipeline|auto)$")


@router.post("/build-agent")
async def build_agent(
    body: BuildAgentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Use an LLM to generate an agent or pipeline config from a natural language description."""
    try:
        from engine.llm_router import LLMRouter

        llm = LLMRouter()
    except Exception as e:
        return error(f"LLM not available: {e}", 500)

    tools_list = "\n".join(
        f"- {name}: {desc}"
        for name, desc in await _get_tools_filtered(str(user.tenant_id))
    )

    # Dynamic context — loaded from database, not hardcoded
    mcp_context = await _get_mcp_registry(db)
    saved_tools_context = await _get_saved_tools_context(db, str(user.tenant_id))
    existing_agents_context = await _get_existing_agents_context(
        db, str(user.tenant_id)
    )
    code_assets_context = await _get_code_assets_context(db, str(user.tenant_id))
    pipeline_examples_context = await _get_pipeline_examples_context()
    sandbox_policy_context = await _get_sandbox_policy_context(str(user.tenant_id))

    system_prompt = f"""You are an expert AI agent architect for the Abenix platform.
Given a user's description, generate a complete agent or pipeline configuration.
{sandbox_policy_context}

AVAILABLE BUILT-IN TOOLS:
{tools_list}

{saved_tools_context}

{PIPELINE_FEATURES}

{mcp_context}

{existing_agents_context}

{code_assets_context}

{pipeline_examples_context}

KNOWLEDGE BASE INTEGRATION:
- Agents with attached knowledge bases automatically get knowledge_search and knowledge_store tools
- knowledge_search: Hybrid search (vector + graph) for retrieval from the knowledge base
- knowledge_store: Write content into the knowledge base (vector embeddings + optional Cognify entity extraction into Neo4j knowledge graph)
- Use knowledge_store with cognify=true to build a knowledge graph from extracted data
- Use knowledge_search to query across all indexed documents

INPUT VARIABLE TYPES: string, number, boolean, url, file, select

RULES:
1. Choose "agent" mode for open-ended tasks where the LLM decides tool order
2. Choose "pipeline" mode for deterministic multi-step workflows with defined data flow
3. If mode is "auto", decide based on the description
4. For pipelines: include nodes with proper depends_on, conditions, and template variables
5. For agents: write a detailed system prompt instructing the LLM how to use tools
6. Always include 2-3 example_prompts showing realistic usage
7. Always include relevant input_variables with descriptions
8. Use snake_case for node IDs
9. ONLY use parameter values that are explicitly listed in a tool's enum options. For example, if a tool's format param is enum[json|csv|txt|markdown|html], do NOT use xlsx, pdf, or any value outside that list
10. Read each tool's parameter list carefully. Do not assume capabilities that are not described. If a tool's description does not mention a feature, assume the tool does not have that feature
11. If NO existing tool can fulfill a step, propose a NEW custom tool. Add it to the "tools" list with a snake_case name and describe it in "custom_tools". The platform will auto-generate the tool implementation. Prefer this over misusing an existing tool with unsupported parameters. For example, if the user needs Excel export and data_exporter only supports csv/json/txt, propose a new "excel_exporter" tool rather than passing format: "xlsx" to data_exporter
12. Only use existing built-in tools when their described capabilities are a genuine match. When in doubt, propose a custom tool — a purpose-built tool is always better than a misused generic one
13. TEMPLATE/CONTEXT DISCIPLINE — {{context.X}} MUST match an input_variable you declared. If you reference {{context.forecast_days}}, you MUST declare input_variables: [{{"name": "forecast_days", ...}}]. Do NOT rename variables between declaration and use. Reference upstream node output as {{node_id.response}} or {{node_id.response.field}} — never invent keys
14. BRANCH MERGING — whenever TWO OR MORE nodes fan in to a single downstream node (i.e. the downstream node has multiple depends_on entries), insert a `data_merger` (or built-in `__merge__`) node in between. Without this, downstream nodes see only one branch's output. Example: if `trends` and `forecast` both feed `correlate`, add a `merge_trends_forecast` node with tool_name=`data_merger` and depends_on=[trends, forecast], and make `correlate` depends_on=[merge_trends_forecast]
15. NEVER INVENT TOOL NAMES — every entry in "tools" and every node's tool_name MUST either (a) appear verbatim in the AVAILABLE BUILT-IN TOOLS list above, or (b) be declared in "custom_tools" in the same response. "fetch_data", "compute_output", "report_x" etc. are not real tools — use http_client + a custom tool instead
16. CODE EXECUTION — decide between `code_executor` and `sandboxed_job` using this ladder, in order:
    a) Pure Python, stdlib + pandas/numpy/math only, <10s runtime, <50KB output → ALWAYS `code_executor` (in-process, AST-validated, ~100ms overhead, no container startup).
    b) Needs a binary NOT in Python stdlib (ffmpeg, pandoc, imagemagick, playwright, poppler, pdftotext, git, rsync, kubectl, etc.) → `sandboxed_job` with the image that ships it.
    c) CPU/memory budget > 1GB OR runtime > 10s OR untrusted/user-provided code → `sandboxed_job` (its per-pod CPU+mem caps and activeDeadline protect the API).
    d) Needs a different runtime entirely (Node, Go, R, Julia) → `sandboxed_job` with that runtime's image.
    e) Needs real isolation from the API (hostile input, exploit research, licence-incompatible code) → `sandboxed_job`.
    Prefer `code_executor` when in doubt — it's ~50× faster for small jobs. Use `sandboxed_job` only when (b)-(e) apply.
17. MEETING / VOICE / CALL AGENTS — when the user asks for an agent that joins a meeting, answers on calls, represents them on a standup, moderates a panel, takes voice questions, or anything where the agent consumes/produces live audio, use these tools in this shape:
    * meeting_join, meeting_listen, meeting_speak, meeting_post_chat, meeting_leave — the provider-agnostic transport layer
    * scope_gate — deterministic answer/defer/decline classifier against user-declared topic lists
    * defer_to_human — ALWAYS include this for voice agents; commitment-shaped questions MUST defer
    * persona_rag — retrieve from the user's ring-fenced persona KB (scope='self' by default)
    The system_prompt MUST include: (a) a hard rule that the bot plays a consent disclosure on join (meeting_join does this automatically), (b) a hard rule that commitment-shaped questions defer, (c) a rule that the bot NEVER speaks more than ~200 chars per utterance, (d) a rule that the bot honors "bot leave" voice commands (meeting_listen flags these). Iteration budget should be 30-40 for meeting agents — they run a listen→decide loop many times.
    Input variables: take `message` as "meeting_id=<uuid>" (the user authorizes the meeting in /meetings first).
    If the user says "use my voice" / "sound like me" / "my cloned voice", include `voice_id: "<user_voice_id>"` on meeting_speak calls — the server-side consent gate will fall back to a neutral voice if consent isn't recorded.
    NEVER build a meeting agent WITHOUT scope_gate + defer_to_human. A meeting agent with no safety rails is a hallucinate-into-a-live-call risk.

Respond ONLY with valid JSON matching this exact schema:
{{
  "name": "Agent/Pipeline Name",
  "description": "1-2 sentence description",
  "mode": "agent" or "pipeline",
  "system_prompt": "Detailed system prompt for LLM behavior...",
  "tools": ["tool1", "tool2"],
  "custom_tools": [
    {{"name": "tool_name", "description": "Detailed description of what this tool does, its expected inputs, outputs, and any libraries it should use (e.g. openpyxl for Excel). Be specific — this description drives code generation.", "parameters": [{{"name": "param", "type": "string", "required": true, "description": "What this param does"}}]}}
  ],
  "input_variables": [
    {{"name": "var_name", "type": "string", "description": "...", "required": true}}
  ],
  "example_prompts": ["Example 1...", "Example 2..."],
  "pipeline_config": {{
    "nodes": [
      {{"id": "node_id", "tool_name": "tool", "arguments": {{}}, "depends_on": []}}
    ],
    "edges": [
      {{"source": "node1", "target": "node2"}}
    ]
  }}
}}

For agent mode, set pipeline_config to null.
For pipeline mode, system_prompt can be empty string.
If no custom tools are needed, set custom_tools to an empty array.

Also include if relevant:
  "suggested_mcp_servers": [
    {{"registry_id": "slack-mcp", "name": "Slack", "reason": "Why this MCP fits", "tools": ["tool1"]}}
  ]
If no MCP is relevant, set suggested_mcp_servers to an empty array.

GUARDRAILS — these are hard rules. A config that violates any of them will
be sent back for repair. Before you emit your JSON, MENTALLY CHECK each one:

  [G1] NAME CONSISTENCY — every `{{{{context.X}}}}` template has a matching
       `{{"name": "X"}}` entry in input_variables. Same spelling, same case.

  [G2] TOOL NAMES ARE REAL — every entry in `tools` and every node's
       `tool_name` is either (a) in the AVAILABLE BUILT-IN TOOLS list above,
       or (b) declared in this same response's `custom_tools` array. If
       neither applies, you MUST add it to custom_tools with a full
       description. Do NOT output dangling names.

  [G3] FAN-IN NEEDS A MERGER — if any node has len(depends_on) ≥ 2, insert
       a `data_merger` (tool_name="data_merger") or `__merge__` node before
       it. The downstream node should depend on the merger, not on the raw
       branches.

  [G4] UPSTREAM REFS ARE REAL — every `{{{{node_id.field}}}}` template
       references a node id that appears earlier in the pipeline (with that
       node in `depends_on` or transitively reachable). No forward refs, no
       typos in node ids.

  [G5] ENUM VALUES ARE LITERAL — if a tool's param is `enum[a|b|c]`, you
       MUST pick one of a/b/c. Using anything else is a hard error.

  [G6] NO HALLUCINATED FIELDS — `{{{{node.response}}}}` is the generic
       output; subfields like `{{{{node.response.prices}}}}` only work if
       that tool's output actually contains that key. When unsure, use
       `{{{{node.response}}}}` or `{{{{node.__all__}}}}`.

  [G7] SNAKE_CASE EVERYTHING — node ids, input_variable names, custom_tool
       names. No camelCase, no hyphens.

  [G8] NODES EARNED THEIR KEEP — every non-terminal node's output must be
       referenced somewhere downstream, either via depends_on or a template.
       Orphan nodes will be removed.
════════════════════════════════════════════════════════════════════════════"""

    user_msg = (
        f"Build an agent/pipeline for: {body.description}\nRequested mode: {body.mode}"
    )

    try:
        response = await llm.complete(
            messages=[{"role": "user", "content": user_msg}],
            system=system_prompt,
            model=(await _get_setting("ai_builder.model")),
            temperature=0.3,
            # Large pipelines with many nodes + long prompts routinely exceed
            # the default 4096. 8192 is the practical sweet spot; going higher
            # mainly buys latency with no quality gain.
            max_tokens=8192,
        )

        text = response.content.strip()
        try:
            config = _parse_builder_json(text, getattr(response, "stop_reason", None))
        except ValueError as e:
            # Surface the concrete cause so the UI can show something actionable.
            return error(str(e), 500)

        # Normalize: auto-union every node tool_name into the `tools` array.
        # The LLM routinely forgets to include e.g. data_merger in tools[]
        # even when it uses it in a node, which the judge then flags as
        # "undeclared". Deterministic fix before validators run.
        from engine.ai_builder_loop import normalize_config

        config = normalize_config(config)

        # Validate required fields
        required = ["name", "description", "mode", "tools"]
        for field in required:
            if field not in config:
                return error(f"Missing field: {field}", 500)

        # Validate tools exist — generate dynamic tools for unknown ones
        valid_tools = {t[0] for t in _get_tools()} | {
            "__switch__",
            "__merge__",
            "wait",
            "state_get",
            "state_set",
        }
        invalid = [t for t in config.get("tools", []) if t not in valid_tools]
        dynamic_tools: list[dict[str, Any]] = []

        if invalid:
            # Try to generate dynamic tools for unknown tool names
            # Use the AI's rich custom_tools descriptions when available
            from engine.tools.dynamic_tool import generate_dynamic_tool

            custom_tools_meta = {
                ct["name"]: ct
                for ct in config.get("custom_tools", [])
                if isinstance(ct, dict)
            }
            for tool_name in invalid:
                try:
                    ct = custom_tools_meta.get(tool_name)
                    if ct and ct.get("description"):
                        # Use the AI's detailed description for high-quality generation
                        param_hints = ", ".join(
                            f'{p["name"]} ({p.get("type", "string")}): {p.get("description", "")}'
                            for p in ct.get("parameters", [])
                        )
                        desc = (
                            f'{ct["description"]}. Parameters: {param_hints}'
                            if param_hints
                            else ct["description"]
                        )
                    else:
                        desc = f"A tool called '{tool_name}' that performs: {tool_name.replace('_', ' ')}"
                    dyn_tool = await generate_dynamic_tool(desc, tool_name)
                    if dyn_tool:
                        tool_params = (
                            [
                                {
                                    "name": p["name"],
                                    "type": p.get("type", "string"),
                                    "required": p.get("required", False),
                                    "description": p.get("description", ""),
                                }
                                for p in dyn_tool.input_schema.get(
                                    "properties", {}
                                ).values()
                            ]
                            if isinstance(dyn_tool.input_schema.get("properties"), dict)
                            else []
                        )
                        dynamic_tools.append(
                            {
                                "name": dyn_tool.name,
                                "description": dyn_tool.description,
                                "code": dyn_tool._code,
                                "parameters": tool_params,
                                "input_schema": dyn_tool.input_schema,
                                "generated": True,
                            }
                        )
                        valid_tools.add(tool_name)

                        # Auto-save to tool library for persistence and reuse
                        try:
                            from models.saved_tool import SavedTool

                            existing = await db.execute(
                                select(SavedTool).where(
                                    SavedTool.tenant_id == user.tenant_id,
                                    SavedTool.name == tool_name,
                                )
                            )
                            if not existing.scalar_one_or_none():
                                saved = SavedTool(
                                    tenant_id=user.tenant_id,
                                    name=dyn_tool.name,
                                    description=dyn_tool.description,
                                    code=dyn_tool._code,
                                    input_schema=dyn_tool.input_schema,
                                    created_by=user.id,
                                    status="approved",  # AI-generated as part of build — auto-approve
                                    permissions={
                                        "network": False,
                                        "filesystem_read": False,
                                        "filesystem_write": False,
                                        "third_party": [],
                                        "env_vars": [],
                                    },
                                )
                                db.add(saved)
                                await db.flush()
                        except Exception:
                            pass  # Save is best-effort; tool still works in-memory
                except Exception:
                    pass

            # Remove any still-invalid tools
            config["tools"] = [t for t in config["tools"] if t in valid_tools]

        # Validate pipeline nodes if pipeline mode
        issues: list[str] = []
        if config.get("mode") == "pipeline" and config.get("pipeline_config"):
            nodes = config["pipeline_config"].get("nodes", [])
            node_ids = {n["id"] for n in nodes}
            for node in nodes:
                node["depends_on"] = [
                    d for d in node.get("depends_on", []) if d in node_ids
                ]
                if node.get("tool_name") not in valid_tools:
                    issues.append(
                        f"Node {node['id']}: unknown tool {node.get('tool_name')}"
                    )
                    node["tool_name"] = "llm_call"
            # Ensure edges reference valid nodes
            edges = config["pipeline_config"].get("edges", [])
            config["pipeline_config"]["edges"] = [
                e
                for e in edges
                if e.get("source") in node_ids and e.get("target") in node_ids
            ]

        # Pass 2: LLM validation — verify the generated config makes sense
        validation_issues: list[str] = []
        if not config.get("system_prompt") and config.get("mode") == "agent":
            validation_issues.append("Agent mode requires a system_prompt")
        if config.get("mode") == "pipeline":
            nodes = config.get("pipeline_config", {}).get("nodes", [])
            if len(nodes) < 2:
                validation_issues.append("Pipeline should have at least 2 nodes")
            # Check all nodes have at least one connection
            connected = set()
            for e in config.get("pipeline_config", {}).get("edges", []):
                connected.add(e.get("source"))
                connected.add(e.get("target"))
            for n in nodes:
                for d in n.get("depends_on", []):
                    connected.add(d)
                    connected.add(n["id"])
            orphans = [
                n["id"] for n in nodes if n["id"] not in connected and len(nodes) > 1
            ]
            if orphans:
                validation_issues.append(f"Orphan nodes (not connected): {orphans}")
        if not config.get("example_prompts"):
            validation_issues.append("Missing example_prompts")
        if not config.get("input_variables"):
            validation_issues.append("Missing input_variables")

        # Pass 2: LLM review of the generated config for correctness
        try:
            review_prompt = f"""Review this generated agent/pipeline config for correctness.
Original request: {body.description}
Generated config (summary):
- Name: {config.get('name')}
- Mode: {config.get('mode')}
- Tools: {config.get('tools')}
- Nodes: {[n['id'] + '(' + n['tool_name'] + ')' for n in (config.get('pipeline_config', {}).get('nodes', []) if config.get('pipeline_config') else [])]}
- Input variables: {[v['name'] for v in config.get('input_variables', [])]}

Custom tools proposed: {[ct.get('name') + ': ' + ct.get('description', '')[:100] for ct in config.get('custom_tools', [])]}

Check for:
1. Does the config actually solve the user's request?
2. Are the tools appropriate for each step? Is any tool being used with parameters or formats it does not support?
3. Are dependencies between nodes correct (DAG order)?
4. Are there any logical gaps (missing steps)?
5. Are template variables like {{{{node_id.__all__}}}} used correctly?

Respond ONLY with JSON: {{"score": 1-10, "issues": ["issue1", "issue2"], "suggestions": ["suggestion1"]}}"""

            review_resp = await llm.complete(
                messages=[{"role": "user", "content": review_prompt}],
                system="You are a config reviewer. Be concise. Respond with JSON only.",
                model=(await _get_setting("ai_builder.critic.model")),
                temperature=0.1,
            )
            review_text = review_resp.content.strip()
            if "{" in review_text:
                review_json = json.loads(
                    review_text[review_text.index("{") : review_text.rindex("}") + 1]
                )
                config["review_score"] = review_json.get("score", 0)
                validation_issues.extend(review_json.get("issues", []))
                config["suggestions"] = review_json.get("suggestions", [])
        except Exception:
            pass  # Review is best-effort, don't fail the whole generation

        repair_info: dict[str, Any] = {"attempted": False}
        if config.get("mode") == "pipeline":
            try:
                from engine.agent_executor import build_tool_registry
                from engine.pipeline_validator import validate_pipeline
                from engine.pipeline_validator_semantic import validate_semantic

                nodes_cfg = (config.get("pipeline_config") or {}).get("nodes") or []
                input_var_names = {
                    v.get("name")
                    for v in (config.get("input_variables") or [])
                    if isinstance(v, dict) and v.get("name")
                }
                registry = build_tool_registry(config.get("tools", []) or [])
                t1 = validate_pipeline(
                    nodes_cfg, registry, available_context_keys=input_var_names
                )
                t2 = validate_semantic(nodes_cfg, registry, tier1=t1)
                concrete_errors = (t1.errors or []) + (t2.errors or [])
                if concrete_errors:
                    repair_info["attempted"] = True
                    repair_info["original_errors"] = [
                        e.to_dict() for e in concrete_errors[:12]
                    ]
                    err_lines = "\n".join(
                        f"  - {e.node_id or '(pipeline)'}/{e.field or ''}: {e.message}"
                        for e in concrete_errors[:15]
                    )
                    repair_user = (
                        "The pipeline you just produced has concrete validator errors. "
                        "Fix ALL of them and return the FULL corrected JSON (same schema, "
                        "no prose).\n\nRules you violated:\n"
                        " • Every {{context.X}} reference MUST match an input_variable name "
                        "you declare.\n"
                        " • Every tool in 'tools' and every node's tool_name MUST be a real "
                        "platform tool or declared in custom_tools.\n"
                        " • When two branches fan in to one node, add a data_merger or "
                        "__merge__ node in between.\n"
                        " • Use snake_case consistently for node IDs and input_variables.\n\n"
                        f"Errors:\n{err_lines}\n\n"
                        f"Original user request: {body.description}\n\n"
                        f"Current (broken) config:\n```json\n{json.dumps(config)[:6000]}\n```"
                    )
                    try:
                        repair_resp = await llm.complete(
                            messages=[{"role": "user", "content": repair_user}],
                            system="You are a config repair specialist. Return ONLY the corrected JSON, no prose.",
                            model=(await _get_setting("ai_builder.model")),
                            temperature=0.0,
                            max_tokens=8192,
                        )
                        repaired = _parse_builder_json(
                            repair_resp.content,
                            getattr(repair_resp, "stop_reason", None),
                        )
                        if (
                            isinstance(repaired, dict)
                            and repaired.get("name")
                            and repaired.get("tools")
                        ):
                            # Re-run validators on the repaired config to record residual errors.
                            r_nodes = (repaired.get("pipeline_config") or {}).get(
                                "nodes"
                            ) or []
                            r_inputs = {
                                v.get("name")
                                for v in (repaired.get("input_variables") or [])
                                if isinstance(v, dict) and v.get("name")
                            }
                            r_reg = build_tool_registry(repaired.get("tools", []) or [])
                            r_t1 = validate_pipeline(
                                r_nodes, r_reg, available_context_keys=r_inputs
                            )
                            r_t2 = validate_semantic(r_nodes, r_reg, tier1=r_t1)
                            residual = (r_t1.errors or []) + (r_t2.errors or [])
                            repair_info["residual_errors"] = [
                                e.to_dict() for e in residual[:10]
                            ]
                            repair_info["fixed_count"] = len(concrete_errors) - len(
                                residual
                            )
                            config = repaired
                    except Exception as e:
                        repair_info["error"] = str(e)[:200]
            except Exception:
                pass  # Auto-repair is best-effort.

        return success(
            {
                **config,
                "generated_by": "ai",
                "model_used": response.model,
                "generation_cost": response.cost,
                "validation_issues": validation_issues + issues,
                "dynamic_tools": dynamic_tools,
                "auto_repair": repair_info,
            }
        )

    except Exception as e:
        return error(f"Generation failed: {e}", 500)


class GenerateToolRequest(BaseModel):
    description: str = Field(..., min_length=5, max_length=2000)
    tool_name: str | None = None


@router.post("/generate-tool")
async def generate_tool_endpoint(
    body: GenerateToolRequest,
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Generate a custom dynamic tool from a description with adversarial review."""
    from engine.tools.dynamic_tool import (
        generate_dynamic_tool,
        _adversarial_review,
    )

    try:
        from engine.llm_router import LLMRouter

        llm = LLMRouter()
    except Exception as e:
        return error(f"LLM not available: {e}", 500)

    tool_name = body.tool_name or (
        "custom_" + body.description[:20].lower().replace(" ", "_")
    )
    tool_name = "".join(c for c in tool_name if c.isalnum() or c == "_")

    # Generate the tool
    dyn_tool = await generate_dynamic_tool(body.description, tool_name)
    if not dyn_tool:
        return error(
            "Failed to generate tool — code validation or adversarial review blocked it",
            400,
        )

    # Run adversarial review for transparency
    review = await _adversarial_review(llm, dyn_tool._code, body.description, [])

    return success(
        {
            "name": dyn_tool.name,
            "description": dyn_tool.description,
            "code": dyn_tool._code,
            "parameters": list(dyn_tool.input_schema.get("properties", {}).keys()),
            "input_schema": dyn_tool.input_schema,
            "review": {
                "safe": review.get("safe", True),
                "score": review.get("score", 0),
                "issues": review.get("issues", []),
                "blocked": review.get("blocked", False),
                "assessment": review.get("review", ""),
            },
            "ast_validation": "passed",
        }
    )


async def _generate_config_core(
    description: str,
    mode: str,
    repair_context: str,
    llm: Any,
    db: AsyncSession,
    user: "User",
) -> dict[str, Any]:
    """Minimal re-implementation of build_agent's core generation for the loop."""
    tools_list = "\n".join(
        f"- {name}: {desc}"
        for name, desc in await _get_tools_filtered(str(user.tenant_id))
    )
    mcp_context = await _get_mcp_registry(db)
    saved_tools_context = await _get_saved_tools_context(db, str(user.tenant_id))
    existing_agents_context = await _get_existing_agents_context(
        db, str(user.tenant_id)
    )
    code_assets_context = await _get_code_assets_context(db, str(user.tenant_id))
    pipeline_examples_context = await _get_pipeline_examples_context()
    sandbox_policy_context = await _get_sandbox_policy_context(str(user.tenant_id))

    system_prompt = f"""You are an expert AI agent architect for Abenix.
Given a description, generate a complete agent or pipeline configuration.
{sandbox_policy_context}
AVAILABLE BUILT-IN TOOLS:
{tools_list}

{saved_tools_context}
{PIPELINE_FEATURES}
{mcp_context}
{existing_agents_context}
{code_assets_context}
{pipeline_examples_context}

RULES:
1. Choose "agent" mode for open-ended tasks; "pipeline" for deterministic DAG workflows.
2. For pipelines: include depends_on, templates, and example_prompts.
3. Use snake_case node IDs.
4. Respond with JSON only, no preamble or fences, matching:
{{
  "name": "...",
  "description": "...",
  "mode": "agent" | "pipeline",
  "system_prompt": "...",
  "tools": ["..."],
  "custom_tools": [],
  "input_variables": [{{"name": "...", "type": "string", "required": true}}],
  "example_prompts": ["..."],
  "pipeline_config": {{"nodes": [...], "edges": [...]}} | null
}}

GUARDRAILS (hard rules — validator will reject the config and ask you to fix):
  [G1] Every {{{{context.X}}}} template has a matching {{"name": "X"}} entry in input_variables (same spelling, same case).
  [G2] Every tool in `tools` and every node's `tool_name` is either in the AVAILABLE BUILT-IN TOOLS list above or declared in `custom_tools` in this same response.
  [G3] When 2+ nodes fan in to one downstream node, insert a `data_merger` (or `__merge__`) node in between. Fan-in without a merger silently drops all branches except one.
  [G4] Every {{{{node_id.field}}}} points to a real upstream node id present in this config.
  [G5] Enum param values are picked from the exact enum list — never invented.
  [G6] snake_case for all identifiers.
{repair_context}
"""
    user_msg = f"Build a {mode} for: {description}"
    resp = await llm.complete(
        messages=[{"role": "user", "content": user_msg}],
        system=system_prompt,
        model=(await _get_setting("ai_builder.model")),
        temperature=0.3,
        max_tokens=8192,
    )
    from engine.ai_builder_loop import normalize_config

    return normalize_config(
        _parse_builder_json(resp.content, getattr(resp, "stop_reason", None))
    )


async def _validate_config_core(config: dict[str, Any]) -> dict[str, Any]:
    """Run Tier 1 + Tier 2 validators against a generated config."""
    from engine.agent_executor import build_tool_registry
    from engine.pipeline_validator import validate_pipeline
    from engine.pipeline_validator_semantic import validate_semantic

    tool_names = config.get("tools", []) or []
    nodes = (config.get("pipeline_config") or {}).get("nodes") or []
    try:
        registry = build_tool_registry(tool_names)
    except Exception as e:
        return {
            "tier1": {
                "valid": False,
                "errors": [
                    {
                        "node_id": "",
                        "field": "tools",
                        "message": f"Failed to build tool registry: {e}",
                        "severity": "error",
                        "suggestion": "",
                    }
                ],
                "warnings": [],
            },
            "tier2": {
                "errors": [],
                "warnings": [],
                "suggestions": [],
                "cost_estimate_usd": 0.0,
                "node_cost_breakdown": {},
                "unused_nodes": [],
            },
        }
    t1 = validate_pipeline(nodes, registry) if nodes else None
    t2 = validate_semantic(nodes, registry, tier1=t1) if nodes else None
    return {
        "tier1": t1.to_dict() if t1 else {"valid": True, "errors": [], "warnings": []},
        "tier2": (
            t2.to_dict()
            if t2
            else {
                "errors": [],
                "warnings": [],
                "suggestions": [],
                "cost_estimate_usd": 0.0,
                "node_cost_breakdown": {},
                "unused_nodes": [],
            }
        ),
    }


class BuildIterativeRequest(BaseModel):
    description: str = Field(..., min_length=10, max_length=5000)
    mode: str = Field(default="auto", pattern="^(agent|pipeline|auto)$")
    # Generate → validate-smart (tier1+tier2+tier3) → judge → repair loop.
    # Capped at 20 — beyond that the LLM starts looping on non-fixable
    # issues and you want a human look, not more spending.
    max_iterations: int = Field(default=6, ge=1, le=20)


@router.post("/build-iterative")
async def build_iterative(
    body: BuildIterativeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Server-Sent Events: iteratively generate → validate → judge."""
    from engine.llm_router import LLMRouter
    from engine.ai_builder_loop import run_iterative_build

    try:
        llm = LLMRouter()
    except Exception as e:
        return JSONResponse(
            {"success": False, "error": f"LLM not available: {e}"}, status_code=500
        )

    async def generator_fn(desc: str, mode: str, repair: str) -> dict[str, Any]:
        return await _generate_config_core(desc, mode, repair, llm, db, user)

    async def validator_fn(config: dict[str, Any]) -> dict[str, Any]:
        return await _validate_config_core(config)

    async def critic_fn(config: dict[str, Any], judge_summary: str) -> dict[str, Any]:
        from engine.ai_builder_loop import _critic

        return await _critic(llm, body.description, config, judge_summary)

    async def execute_fn(config: dict[str, Any]) -> dict[str, Any]:
        """Smoke-test the generated pipeline by running it once with a"""
        try:
            mode = (config.get("mode") or "").lower()
            if mode != "pipeline":
                return {"ok": True, "skipped": "non-pipeline mode auto-test skipped"}
            try:
                from engine.agent_executor import build_tool_registry
                from engine.pipeline import PipelineExecutor, parse_pipeline_nodes
            except Exception as e:
                return {"ok": True, "skipped": f"runtime modules unavailable: {e}"}
            pipe_cfg = config.get("pipeline_config") or {}
            raw_nodes = pipe_cfg.get("nodes") or []
            if not raw_nodes:
                return {"ok": False, "error": "pipeline has no nodes"}
            try:
                nodes = parse_pipeline_nodes(raw_nodes)
            except Exception as e:
                return {"ok": False, "error": f"parse_pipeline_nodes failed: {e}"[:500]}
            tool_names = list(config.get("tools") or [])
            try:
                registry = build_tool_registry(
                    tool_names,
                    agent_id="00000000-0000-0000-0000-000000000000",
                    tenant_id=str(user.tenant_id),
                    execution_id="00000000-0000-0000-0000-000000000000",
                    agent_name=config.get("name", "ai-builder-smoke"),
                    db_url=str(settings.database_url),
                )
            except Exception as e:
                return {"ok": True, "skipped": f"tool registry build failed: {e}"[:300]}
            try:
                executor = PipelineExecutor(tool_registry=registry, llm_router=llm)
            except Exception as e:
                return {"ok": True, "skipped": f"executor init failed: {e}"[:300]}
            sample = (config.get("example_prompts") or ["run the pipeline"])[0]
            try:
                result = await executor.execute(nodes, {"message": sample})
            except Exception as e:
                return {
                    "ok": False,
                    "error": f"executor.execute raised: {type(e).__name__}: {e}"[:500],
                }
            status = getattr(result, "status", "")
            if status not in ("completed", "partial"):
                return {
                    "ok": False,
                    "error": f"pipeline status={status}; failed_nodes={getattr(result,'failed_nodes',[])}",
                }
            return {
                "ok": True,
                "status": status,
                "execution_path": getattr(result, "execution_path", []),
                "failed_nodes": getattr(result, "failed_nodes", []),
            }
        except Exception as e:
            return {"ok": False, "error": f"unexpected: {type(e).__name__}: {e}"[:500]}

    async def event_stream():
        loop = run_iterative_build(
            user_request=body.description,
            mode=body.mode,
            max_iterations=body.max_iterations,
            llm=llm,
            generator_fn=generator_fn,
            validator_fn=validator_fn,
            dry_run_fn=None,  # Dry-run probe: follow-up enhancement.
            critic_fn=critic_fn,
            execute_fn=execute_fn,
        )
        try:
            async for event in loop:
                if await request.is_disconnected():
                    break
                name = event.pop("event", "message")
                yield f"event: {name}\ndata: {json.dumps(event, default=str)}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/simulate-meeting")
async def simulate_meeting(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run a meeting agent against a SYNTHETIC transcript — no real room."""
    import json as _json
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(
        0, str(_Path(__file__).resolve().parents[4] / "apps" / "agent-runtime")
    )
    try:
        from engine.tools.scope_gate import ScopeGateTool  # type: ignore
        from engine.tools import _meeting_session as sessmod  # type: ignore
    except ImportError as e:
        return JSONResponse(
            {"success": False, "error": f"agent runtime not reachable: {e}"},
            status_code=500,
        )

    turns = body.get("turns") or []
    scope_allow = [str(s) for s in (body.get("scope_allow") or [])]
    scope_defer = [str(s) for s in (body.get("scope_defer") or [])]
    tools_declared = body.get("tools") or []

    # Structural checks — the fastest way to catch a bad meeting agent
    warnings: list[str] = []
    blockers: list[str] = []
    tools_set = set(tools_declared)
    if "meeting_join" not in tools_set:
        blockers.append(
            "missing meeting_join — the agent cannot participate in any meeting"
        )
    if "meeting_listen" not in tools_set and "meeting_speak" not in tools_set:
        blockers.append(
            "missing both meeting_listen and meeting_speak — this isn't a meeting agent"
        )
    if "scope_gate" not in tools_set:
        warnings.append(
            "missing scope_gate — the agent will rely on LLM judgement to stay in bounds, "
            "which is riskier than the deterministic gate",
        )
    if "defer_to_human" not in tools_set:
        warnings.append(
            "missing defer_to_human — commitment-shaped questions will be answered by the LLM, "
            "which is the #1 source of embarrassing agent behavior"
        )
    if "meeting_leave" not in tools_set:
        warnings.append("missing meeting_leave — the bot has no clean-exit path")

    # System-prompt lint
    sp = (body.get("system_prompt") or "").lower()
    if "defer" not in sp and "defer_to_human" not in sp:
        warnings.append("system prompt never mentions defer — add an explicit rule")
    if "consent" not in sp and "announce" not in sp:
        warnings.append("system prompt never mentions consent disclosure — add a rule")
    if "commit" not in sp and "commitment" not in sp:
        warnings.append(
            "system prompt never mentions commitments — add a defer-for-commitments rule"
        )

    # Per-turn dry-run: register a fake session so scope_gate can read allow/defer
    fake_exec = f"sim-{_json.dumps(sorted(scope_allow + scope_defer))[:40]}"
    sess = sessmod.MeetingSession(
        execution_id=fake_exec,
        meeting_id="sim-meeting",
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        provider="sim",
        room="sim",
        display_name="Sim Bot",
        adapter=None,
        status="live",
        scope_allow=scope_allow,
        scope_defer=scope_defer,
        persona_scopes=["self"],
    )
    sessmod.register(sess)
    gate = ScopeGateTool(execution_id=fake_exec)
    decisions = []
    try:
        for turn in turns:
            q = (turn.get("text") or "").strip()
            if not q:
                continue
            r = await gate.execute({"meeting_id": "sim-meeting", "question": q})
            payload = _json.loads(r.content) if r.content else {}
            decisions.append(
                {
                    "speaker": turn.get("speaker", "?"),
                    "question": q,
                    "decision": payload.get("decision"),
                    "reason": payload.get("reason"),
                }
            )
    finally:
        sessmod.drop(fake_exec)

    counts = {"answer": 0, "defer": 0, "decline": 0}
    for d in decisions:
        if d.get("decision") in counts:
            counts[d["decision"]] += 1

    return JSONResponse(
        {
            "success": True,
            "data": {
                "decisions": decisions,
                "counts": counts,
                "blockers": blockers,
                "warnings": warnings,
                "ready_to_deploy": len(blockers) == 0,
            },
        }
    )
