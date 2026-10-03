"""Agent step tool — run a full AI agent as a pipeline step."""

from __future__ import annotations

import json
from typing import Any

from engine.provider_credentials import PROVIDER_CONFIG_FIELDS
from engine.tools.base import BaseTool, ToolResult


async def _agent_settings(agent_id: str, db_url: str) -> tuple[dict[str, Any], Any]:
    """model_config and per-run cost cap of a saved agent, empty for an inline step or on any failure."""
    if not agent_id or not db_url:
        return {}, None
    try:
        from sqlalchemy import text as _t
        from sqlalchemy.ext.asyncio import AsyncSession

        from engine.pipeline import _get_pipeline_engine

        engine = await _get_pipeline_engine(db_url)
        if engine is None:
            return {}, None
        async with AsyncSession(engine) as session:
            row = (
                await session.execute(
                    _t(
                        "SELECT model_config, per_execution_cost_limit FROM agents "
                        "WHERE id = CAST(:aid AS uuid)"
                    ).bindparams(aid=agent_id)
                )
            ).first()
        cfg = row[0] if row else {}
        if isinstance(cfg, str):
            cfg = json.loads(cfg)
        return (cfg if isinstance(cfg, dict) else {}), (row[1] if row else None)
    except Exception:
        return {}, None


async def _budget_breach(agent_id: str, tenant_id: str, db_url: str) -> Any:
    """The saved agent's daily cap breach, None for an inline step or when the check cannot run."""
    if not agent_id or not tenant_id or not db_url:
        return None
    try:
        from sqlalchemy.ext.asyncio import AsyncSession

        from engine.agent_budget import check_agent_budget_by_id
        from engine.pipeline import _get_pipeline_engine

        engine = await _get_pipeline_engine(db_url)
        if engine is None:
            return None
        async with AsyncSession(engine) as session:
            return await check_agent_budget_by_id(session, agent_id, tenant_id)
    except Exception:
        return None


async def _hold_to_schema(
    router: Any,
    schema: Any,
    system_prompt: str,
    model: str,
    temperature: float,
    task: str,
    output: str,
) -> tuple[str, list[str]]:
    """Check an agent's answer against its declared output_schema, one corrective retry.

    Returns the output to pass on and any violations still left. Agents
    without a schema pass through untouched.
    """
    if not isinstance(schema, dict) or not output:
        return output, []
    from engine.post_process import post_process, schema_violations

    _, warns = post_process(output, schema)
    bad = schema_violations(warns)
    if not bad:
        return output, []
    note = (
        "Your answer does not match the required output format:\n- "
        + "\n- ".join(bad[:15])
        + "\nReturn only the corrected JSON. Do not leave required fields empty. "
        "Anything you cannot fill in completely goes where the format puts unresolved items."
    )
    try:
        resp = await router.complete(
            messages=[
                {"role": "user", "content": task},
                {"role": "assistant", "content": output},
                {"role": "user", "content": note},
            ],
            system=system_prompt or None,
            tools=None,
            model=model,
            temperature=min(float(temperature or 0), 0.2),
            max_tokens=4096,
            stream=False,
        )
        fixed = getattr(resp, "content", "") or ""
    except Exception:  # noqa: BLE001
        return output, bad
    _, warns2 = post_process(fixed, schema)
    bad2 = schema_violations(warns2)
    if fixed and len(bad2) < len(bad):
        return fixed, bad2
    return output, bad


class AgentStepTool(BaseTool):
    # The LLM provider keys, declared here so they sit on the admin screen.
    config_fields = PROVIDER_CONFIG_FIELDS
    name = "agent_step"
    risk_tier = "low"
    description = (
        "Run a full AI agent as a pipeline step. The agent has its own LLM loop, "
        "can use tools, and iterates autonomously until it produces a final answer. "
        "Use this to chain agents within a pipeline — the output of one agent can "
        "feed into another. Supports all available tools and LLM models."
    )

    def __init__(
        self, user_id: str = "", user_role: str = "", delegation_depth: int = 0
    ) -> None:
        # the caller of the pipeline, so tools inside the step act as them
        self._user_id = user_id
        self._user_role = user_role
        self._delegation_depth = delegation_depth

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "input_message": {
                "type": "string",
                "description": "The task or prompt for the agent to work on",
            },
            "system_prompt": {
                "type": "string",
                "description": "System prompt defining the agent's role and behavior",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of tool names available to the agent",
                "default": [],
            },
            "model": {
                "type": "string",
                "description": "LLM model to use",
                "default": "claude-sonnet-4-5-20250929",
            },
            "max_iterations": {
                "type": "integer",
                "description": "Maximum number of LLM reasoning loops",
                "default": 10,
                "minimum": 1,
                "maximum": 25,
            },
            "temperature": {
                "type": "number",
                "description": "Sampling temperature",
                "default": 0.7,
                "minimum": 0,
                "maximum": 2,
            },
        },
        "required": ["input_message", "system_prompt"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        input_message = arguments.get("input_message", "")
        system_prompt = arguments.get("system_prompt", "")
        raw_tools = arguments.get("tools", [])
        # Handle both list and comma-separated string formats
        if isinstance(raw_tools, str):
            tool_names = [t.strip() for t in raw_tools.split(",") if t.strip()]
        elif isinstance(raw_tools, list):
            tool_names = raw_tools
        else:
            tool_names = []
        model = arguments.get("model", "claude-sonnet-4-5-20250929")
        max_iterations = arguments.get("max_iterations", 10)
        temperature = arguments.get("temperature", 0.7)

        # Coerce non-string inputs (from upstream node outputs) to JSON strings
        if not isinstance(input_message, str):
            import json as _j

            input_message = _j.dumps(input_message, default=str, indent=2)
        if not isinstance(system_prompt, str):
            import json as _j

            system_prompt = _j.dumps(system_prompt, default=str, indent=2)

        if not input_message.strip():
            return ToolResult(content="Error: input_message is required", is_error=True)
        if not system_prompt.strip():
            return ToolResult(content="Error: system_prompt is required", is_error=True)

        import os as _os

        breach = await _budget_breach(
            str(arguments.get("__agent_id__") or ""),
            str(arguments.get("__tenant_id__") or ""),
            _os.environ.get("DATABASE_URL", ""),
        )
        if breach is not None:
            return ToolResult(
                content=f"Budget exceeded: {breach.message}",
                is_error=True,
                metadata={"failure_code": "BUDGET_EXCEEDED", **breach.details()},
            )

        try:
            from engine.agent_executor import AgentExecutor, build_tool_registry
            from engine.llm_router import LLMRouter
            from engine.sandbox import ExecutionSandbox, SandboxPolicy

            # Build a sub-agent with its own sandbox (reduced limits to prevent runaway)
            # fixed limits cut off any agent that walks more steps than they allow, whatever its own max_iterations said
            iters = int(max_iterations or 0)
            sub_policy = dict(
                max_tool_calls=max(20, 2 * iters), max_output_chars=50_000
            )
            if iters > 10:
                sub_policy.update(timeout_seconds=30 * iters, timeout_overridden=True)
            sub_sandbox = ExecutionSandbox(SandboxPolicy(**sub_policy))

            # The pipeline passes the sub-agent's execution context under
            # dunder keys. Without them the registry silently drops
            # knowledge_search and every db-backed tool, and the agent replies
            # that it has no way to look anything up.
            import os as _os

            # the agent's own tool settings, e.g. which code asset it is bound to
            child_agent_id = str(arguments.get("__agent_id__") or "")
            agent_cfg, cost_cap = await _agent_settings(
                child_agent_id, _os.environ.get("DATABASE_URL", "")
            )
            tool_cfg = agent_cfg.get("tool_config") or {}
            if tool_cfg:
                from engine.agent_executor import resolve_asset_schemas
                from engine.tool_config_prompt import build_tool_config_prompt

                system_prompt = build_tool_config_prompt(system_prompt, tool_cfg)
                asset_schemas = await resolve_asset_schemas(
                    tool_cfg, tenant_id=str(arguments.get("__tenant_id__") or "")
                )
            else:
                asset_schemas = {}

            tool_registry = build_tool_registry(
                tool_names or [],
                kb_ids=arguments.get("__kb_ids__") or [],
                agent_id=str(arguments.get("__agent_id__") or ""),
                tenant_id=str(arguments.get("__tenant_id__") or ""),
                db_url=_os.environ.get("DATABASE_URL", ""),
                user_id=getattr(self, "_user_id", ""),
                user_role=getattr(self, "_user_role", ""),
                delegation_depth=getattr(self, "_delegation_depth", 0),
                model_config=agent_cfg,
            )
            router = LLMRouter()

            executor = AgentExecutor(
                llm_router=router,
                tool_registry=tool_registry,
                system_prompt=system_prompt,
                model=model,
                temperature=temperature,
                max_iterations=max_iterations,
                sandbox=sub_sandbox,
                tool_config=tool_cfg or None,
                asset_schemas=asset_schemas or None,
                cost_limit=cost_cap,
            )

            result = await executor.invoke(input_message)
            # the child's spend is read back from this metadata for its own daily caps
            billing = {"billed_agent_id": child_agent_id} if child_agent_id else {}
            if getattr(result, "budget_exceeded", False):
                return ToolResult(
                    content=f"Budget exceeded: {result.output}",
                    is_error=True,
                    metadata={
                        **billing,
                        "failure_code": "BUDGET_EXCEEDED",
                        "model": result.model,
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "cost": result.cost,
                    },
                )
            final_output, schema_warnings = await _hold_to_schema(
                router,
                agent_cfg.get("output_schema"),
                system_prompt,
                model,
                temperature,
                input_message,
                result.output,
            )

            output = {
                "response": final_output,
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost": result.cost,
                "duration_ms": result.duration_ms,
                "tool_calls_count": len(result.tool_calls) if result.tool_calls else 0,
                "iterations": len(result.node_traces) if result.node_traces else 0,
            }

            return ToolResult(
                content=json.dumps(output, indent=2, default=str),
                metadata={
                    **billing,
                    **(
                        {"validation_warnings": schema_warnings}
                        if schema_warnings
                        else {}
                    ),
                    "model": result.model,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "cost": result.cost,
                    "tool_calls_count": (
                        len(result.tool_calls) if result.tool_calls else 0
                    ),
                },
            )

        except Exception as e:
            return ToolResult(content=f"Agent step failed: {e}", is_error=True)
