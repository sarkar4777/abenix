from __future__ import annotations

import functools
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

from engine import credentials, governance, risk
from engine.credentials import ToolNeedsConfiguration

__all__ = [
    "READ_ONLY",
    "BaseTool",
    "ConfigField",
    "Effect",
    "ToolNeedsConfiguration",
    "ToolRegistry",
    "ToolResult",
    "needs_configuration_result",
]


@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConfigField:
    """One value a tool needs, declared on the tool class.

    ``key`` is the environment-style name the tool reads, which is also what
    the admin screen stores it under. ``group`` is the provider the screen
    groups by. ``dynamic`` marks a field that is read under a name built at
    run time, so the lint does not expect a literal reference to it.
    """

    key: str
    label: str = ""
    kind: str = "secret"  # secret | string | url | int | bool | select
    required: bool = False
    group: str = ""
    description: str = ""
    signup_url: str = ""
    default: str | None = None
    options: tuple[str, ...] = ()
    dynamic: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["options"] = list(self.options)
        return d


@dataclass(frozen=True)
class Effect:
    """What a call does to the world, declared on the tool class."""

    kind: str  # read | write | send | publish | control | trade | delete | external
    label: str
    target_param: str | None = None
    magnitude_param: str | None = None
    reversible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


READ_ONLY = Effect(kind="read", label="Read only")


AUTONOMY_ARGS = ("_intent", "_prediction")


def strip_autonomy_args(arguments: Any) -> Any:
    """Drop the autonomy-only arguments before a tool sees them."""
    if isinstance(arguments, dict) and any(k in arguments for k in AUTONOMY_ARGS):
        return {k: v for k, v in arguments.items() if k not in AUTONOMY_ARGS}
    return arguments


def needs_configuration_result(tool: Any, exc: ToolNeedsConfiguration) -> ToolResult:
    """The one message every tool gives when a required value is missing."""
    fld = None
    for f in getattr(tool, "config_fields", ()) or ():
        if f.key == exc.key:
            fld = f
            break
    signup = exc.signup_url or (fld.signup_url if fld else "")
    text = (
        f"{exc.key} is not configured. "
        "An admin can add it under Admin -> Tool Configuration."
    )
    if signup:
        text += f" Get a key at {signup}"
    return ToolResult(
        content=text,
        is_error=True,
        metadata={
            "needs_configuration": exc.key,
            "signup_url": signup,
            "tool": getattr(tool, "name", ""),
        },
    )


async def _govern(
    tool: Any, arguments: dict[str, Any], gate_out: list[Any] | None = None
) -> ToolResult | None:
    """Kill switches, autonomy and tier escalation for one tool call. None means go ahead."""
    run = governance.current()
    tenant = (
        run.tenant_id
        if run
        else credentials.current_tenant() or str(getattr(tool, "tenant_id", "") or "")
    )
    name = getattr(tool, "name", "")
    try:
        governance.check(tenant, "tool", name)
        # a run already going stops at its next tool call, nested runs included
        for ctx in run.chain() if run else ():
            if ctx.subject_id:
                governance.check(tenant, ctx.scope, ctx.subject_id)
    except governance.Stopped as s:
        return ToolResult(
            content=s.message(),
            is_error=True,
            metadata={"stopped": {"scope": s.scope, "target": s.target}, "tool": name},
        )
    from engine import autonomy

    # an action let through goes back in gate_out, the caller closes it after the call
    action = await autonomy.gate(tool, arguments, run, tenant)
    if action is not None and action.result is not None:
        return action.result
    if action is not None:
        arguments = action.arguments
        if gate_out is not None:
            gate_out.append(action)
    refused = await _tier_check(tool, arguments, run, tenant, name, action)
    if refused is not None and action is not None:
        action.refused(refused)
    return refused


async def _tier_check(
    tool: Any,
    arguments: dict[str, Any],
    run: Any,
    tenant: str,
    name: str,
    action: Any = None,
) -> ToolResult | None:
    tier = risk.normalize(getattr(tool, "risk_tier", "low"))
    if run is None or not risk.above(tier, run.tier):
        return None
    action_kind = governance.policy(tenant, tier).get("tool_call_action", "allow")
    if action_kind == "block":
        return ToolResult(
            content=(
                f"{name} is a {tier} risk tool and this run is {run.tier} risk. "
                f"The tenant's {tier} tier policy blocks the call. Raise the agent's "
                f"risk tier to {tier} if it should use this tool."
            ),
            is_error=True,
            metadata={
                "risk_blocked": {"tool_tier": tier, "run_tier": run.tier},
                "tool": name,
            },
        )
    if action_kind == "approval" and action is not None and action.approved_by:
        # a person already approved this exact call at the tool's tier
        run.raise_to(tier, f"tool:{name}", f"approved by {action.approved_by}")
        return None
    if action_kind == "approval":
        from engine.tools.human_approval import HumanApprovalTool

        import json as _json

        gate = HumanApprovalTool(
            execution_id=run.execution_id,
            tenant_id=tenant,
            agent_name=run.agent_name,
        )
        decision = await gate.execute(
            {
                "action": f"call {name} ({tier} risk)",
                "details": _json.dumps(arguments or {}, default=str)[:4000],
                "risk_level": tier,
            }
        )
        if decision.is_error:
            return ToolResult(
                content=f"{name} needs approval at {tier} risk and did not get it. {decision.content}",
                is_error=True,
                metadata={"risk_approval": decision.metadata, "tool": name},
            )
        run.raise_to(
            tier, f"tool:{name}", f"approved by {decision.metadata.get('reviewer', '')}"
        )
        return None
    run.raise_to(tier, f"tool:{name}")
    return None


class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict[str, Any]
    # What this tool needs to run. Empty for a tool that needs nothing.
    config_fields: tuple[ConfigField, ...] = ()
    # low | medium | high | critical, see engine.risk.TIER_GUIDE
    risk_tier: str = "low"
    # what a call changes in the world, None for a tool that only reads
    effect: Effect | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Wrap execute once per class that defines it, so every tool gets the
        # same two things without touching any call site: a fresh snapshot
        # before it runs, and the standard result when it raises for a
        # missing value. Wrappers and dynamic tools are subclasses too.
        original = cls.__dict__.get("execute")
        if original is None or getattr(original, "_config_wrapped", False):
            return

        @functools.wraps(original)
        async def execute(self: BaseTool, arguments: dict[str, Any]) -> ToolResult:
            await credentials.ensure_fresh()
            # wrappers around a tool are checked once, at the outermost call
            gtoken = None
            action = None
            if not governance.in_tool():
                from engine import autonomy

                await governance.ensure_fresh()
                await autonomy.ensure_fresh()
                gate_out: list[Any] = []
                refused = await _govern(self, arguments, gate_out)
                if refused is not None:
                    return refused
                if gate_out:
                    action = gate_out[0]
                    arguments = action.arguments
                gtoken = governance.enter_tool()
            arguments = strip_autonomy_args(arguments)
            # a tool built with its own tenant_id covers reads outside an executor run
            token = None
            own_tenant = str(getattr(self, "tenant_id", "") or "")
            if own_tenant and not credentials.current_tenant():
                token = credentials.set_tenant(own_tenant)
            try:
                try:
                    result = await original(self, arguments)
                except ToolNeedsConfiguration as exc:
                    result = needs_configuration_result(self, exc)
                except BaseException as exc:
                    if action is not None:
                        action.failed(exc)
                    raise
                if action is not None:
                    result = action.finished(result)
                return result
            finally:
                if token is not None:
                    credentials.reset_tenant(token)
                if gtoken is not None:
                    governance.exit_tool(gtoken)

        execute._config_wrapped = True  # type: ignore[attr-defined]
        cls.execute = execute  # type: ignore[assignment]

    @abstractmethod
    async def execute(self, arguments: dict[str, Any]) -> ToolResult: ...

    @classmethod
    def effect_for(cls, arguments: dict[str, Any]) -> Effect | None:
        """The effect of one call. Tools whose operations differ override this."""
        return cls.effect

    @classmethod
    def config_field(cls, key: str) -> ConfigField | None:
        for f in cls.config_fields:
            if f.key == key:
                return f
        return None

    def cfg(
        self, key: str, *, required: bool = False, default: str | None = None
    ) -> str:
        """Read a configured value. See engine.credentials for the order."""
        fld = self.config_field(key)
        if default is None and fld is not None:
            default = fld.default
        tenant = None
        if not credentials.current_tenant():
            tenant = str(getattr(self, "tenant_id", "") or "") or None
        try:
            return credentials.get(
                key, required=required, default=default, tenant_id=tenant
            )
        except ToolNeedsConfiguration as exc:
            if fld is not None:
                exc.signup_url = exc.signup_url or fld.signup_url
                exc.label = exc.label or fld.label
            raise

    @classmethod
    def config_test(
        cls, values: dict[str, str], key: str | None = None
    ) -> tuple[bool, str] | None:
        """Check the given values against the provider, if the tool knows how.

        Return ``(ok, message)``, or ``None`` when the tool has no test. The
        admin screen shows a Test button only for tools that return one.
        """
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "config_fields": [f.to_dict() for f in self.config_fields],
            "risk_tier": risk.normalize(getattr(self, "risk_tier", "low")),
        }


class _DefaultedTool(BaseTool):
    """Transparent wrapper that hides pinned parameter keys and enforces tool_config limits."""

    def __init__(
        self,
        inner: BaseTool,
        defaults: dict[str, Any] | None = None,
        asset_input_schema: dict[str, Any] | None = None,
        *,
        max_calls: int | None = None,
        require_approval: bool = False,
        approval_tool: BaseTool | None = None,
        locked_defaults: bool = True,
    ) -> None:
        self._inner = inner
        self._defaults = defaults or {}
        # locked_defaults: pinned values win over model-supplied ones unless the author opts out.
        self._locked = bool(locked_defaults)
        try:
            self._max_calls = max(int(max_calls or 0), 0)
        except (TypeError, ValueError):
            self._max_calls = 0
        self._require_approval = bool(require_approval)
        self._approval_tool = approval_tool
        self._calls = 0
        self.name = inner.name
        self.config_fields = inner.config_fields
        self.risk_tier = getattr(inner, "risk_tier", "low")
        # Build a filtered schema that removes pre-set keys.
        props = dict((inner.input_schema or {}).get("properties") or {})
        required = list((inner.input_schema or {}).get("required") or [])
        hidden: list[str] = []
        for k in list(self._defaults.keys()):
            if k in props:
                props.pop(k)
                hidden.append(k)
            if k in required:
                required.remove(k)
        # If the caller provided a richer schema for the `input` field
        # (from upload-time discovery), inline it so the LLM knows the
        # exact shape to produce.
        if asset_input_schema and "input" in props:
            props["input"] = {
                **asset_input_schema,
                "description": props["input"].get("description", ""),
            }
        self.input_schema = {
            **(inner.input_schema or {}),
            "properties": props,
            "required": required,
        }
        # Annotate the description so the LLM understands which fields
        # are auto-filled (purely informational — doesn't affect dispatch).
        extra = f" (pre-configured: {', '.join(hidden)})" if hidden else ""
        self.description = (inner.description or "") + extra

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if self._max_calls and self._calls >= self._max_calls:
            return ToolResult(
                content=f"max_calls ({self._max_calls}) reached for {self.name}",
                is_error=True,
                metadata={"max_calls_reached": True, "tool": self.name},
            )
        self._calls += 1

        if self._require_approval:
            if self._approval_tool is None:
                return ToolResult(
                    content="require_approval set but human_approval is not in the agent's tools",
                    is_error=True,
                    metadata={"tool": self.name},
                )
            import json as _json

            gate = await self._approval_tool.execute(
                {
                    "action": f"call {self.name}",
                    "details": _json.dumps(arguments or {}, default=str)[:4000],
                }
            )
            if gate.is_error:
                return ToolResult(
                    content=f"approval denied: {gate.content}",
                    is_error=True,
                    metadata={"tool": self.name, "approval": gate.metadata},
                )

        return await self._inner.execute(self.merged_arguments(arguments))

    def merged_arguments(self, arguments: dict[str, Any] | None) -> dict[str, Any]:
        if self._locked:
            return {**(arguments or {}), **self._defaults}
        return {**self._defaults, **(arguments or {})}

    def effect_for(self, arguments: dict[str, Any]) -> Effect | None:  # type: ignore[override]
        from engine.autonomy import resolve_effect

        return resolve_effect(self._inner, self.merged_arguments(arguments))


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_all(self) -> list[dict[str, Any]]:
        from engine import autonomy

        return [autonomy.describe(t.to_dict(), t) for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def apply_tool_config(
        self,
        tool_config: dict[str, dict[str, Any]] | None,
        asset_schemas: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Wrap every tool that has parameter_defaults (or an asset-"""
        if not tool_config and not asset_schemas:
            return
        tool_config = tool_config or {}
        asset_schemas = asset_schemas or {}
        approval_tool = self._tools.get("human_approval")
        for name, tool in list(self._tools.items()):
            tc = tool_config.get(name) or {}
            defaults = tc.get("parameter_defaults") or {}
            asset_schema = (asset_schemas.get(name) or {}).get("input_schema")
            max_calls = tc.get("max_calls") or 0
            # The gate cannot gate itself.
            require_approval = (
                bool(tc.get("require_approval")) and name != "human_approval"
            )
            if (
                not defaults
                and not asset_schema
                and not max_calls
                and not require_approval
            ):
                continue
            self._tools[name] = _DefaultedTool(
                tool,
                defaults=defaults,
                asset_input_schema=asset_schema,
                max_calls=max_calls,
                require_approval=require_approval,
                approval_tool=approval_tool,
                locked_defaults=tc.get("locked_defaults", True),
            )
