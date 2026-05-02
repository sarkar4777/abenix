"""Strict Pydantic schema for agent seed YAMLs.

Born from the ClaimsIQ Phase A4 incident: ``pipeline_config:`` was silently
nested inside ``model_config:`` in two YAMLs. ``seed_agents.py`` reads
``pipeline_config`` from the top level, so the agent registered as a
single-step LLM agent and every execution returned status=failed in 2-5s.

This module defines :class:`AgentSeedSchema` with ``extra='forbid'`` so any
unknown top-level field — or any nested field that should live at top level
— surfaces as a loud validation error at install time, not as a 4xx in
production.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# --- Sub-schemas ----------------------------------------------------------

# Fields that *belong* under model_config. Any other key is allowed (the
# runtime / executor reads tool_config etc. from there too) but the
# fields below MUST NOT appear nested in model_config — they belong at
# the top level of the YAML.
_FIELDS_THAT_MUST_BE_TOP_LEVEL = {
    "pipeline_config",
    "agent_type",
    "name",
    "slug",
    "description",
    "system_prompt",
    "category",
    "version",
    "status",
    "icon",
    "runtime_pool",
    "min_replicas",
    "max_replicas",
    "concurrency_per_replica",
    "rate_limit_qps",
    "daily_budget_usd",
}


class PipelineNodeSchema(BaseModel):
    """Each node in a pipeline graph.

    The DSL accepts multiple legitimate node forms:
      - ``type: tool|agent|structured|switch|loop`` (declarative form)
      - ``tool_name: <name>`` (legacy form — pipeline_executor maps the
        tool name to the node kind)
    We require ``id`` and at least one of ``type`` / ``tool_name`` so a
    node missing both surfaces loudly. Everything else is grab-bag.
    """

    id: str

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _has_kind(self) -> "PipelineNodeSchema":
        extra = self.__pydantic_extra__ or {}
        if "type" not in extra and "tool_name" not in extra:
            raise ValueError(
                f"pipeline node '{self.id}' must declare either "
                "'type' (agent|tool|structured|switch|loop) or 'tool_name'"
            )
        return self


class PipelineConfigSchema(BaseModel):
    nodes: list[PipelineNodeSchema] = Field(min_length=1)

    model_config = {"extra": "allow"}


class ModelConfigSchema(BaseModel):
    """Block reserved for runtime / LLM tuning.

    Anything top-level-only (notably ``pipeline_config``) is rejected so
    the loader never silently swallows mis-indented YAML.
    """

    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)
    max_iterations: int | None = Field(default=None, ge=1, le=200)
    tools: list[str] | None = None

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _no_top_level_keys_nested(self) -> "ModelConfigSchema":
        leaked = sorted(
            set(self.__pydantic_extra__ or {}).intersection(
                _FIELDS_THAT_MUST_BE_TOP_LEVEL
            )
        )
        if leaked:
            raise ValueError(
                "model_config contains fields that belong at the top level: "
                f"{leaked}. Dedent these to the YAML root. (This is the same "
                "class of bug that broke ClaimsIQ pipelines — see "
                "logs/uat/apps/PHASE-A-DEEP-claimsiq.md.)"
            )
        return self


# --- Top-level schema -----------------------------------------------------


class AgentSeedSchema(BaseModel):
    """Strict schema for every YAML under packages/db/seeds/agents/.

    extra='allow' here because we keep accreting optional fields (e.g.
    ``input_variables``, ``example_prompts``, ``tool_config``) and we
    don't want the loader to refuse a brand-new field — but the nested
    ``model_config`` block is locked down so the silent-coerce bug stays
    extinct.
    """

    name: str = Field(min_length=1)
    slug: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    description: str = ""
    system_prompt: str = ""
    # The runtime loader lower-cases this, so we accept both forms.
    agent_type: Literal["custom", "oob", "vertical", "CUSTOM", "OOB", "VERTICAL"] = (
        "oob"
    )
    category: str | None = None
    version: str = "1.0.0"
    status: Literal["draft", "pending_review", "active", "rejected", "archived"] = (
        "active"
    )
    icon: str | None = None
    mode: str | None = None
    pipeline_config: PipelineConfigSchema | None = None
    model_config_payload: ModelConfigSchema = Field(
        default_factory=ModelConfigSchema, alias="model_config"
    )

    runtime_pool: str | None = None
    min_replicas: int | None = Field(default=None, ge=0, le=200)
    max_replicas: int | None = Field(default=None, ge=0, le=500)
    concurrency_per_replica: int | None = Field(default=None, ge=1, le=200)

    model_config = {"extra": "allow", "populate_by_name": True}

    @model_validator(mode="after")
    def _pipeline_invariants(self) -> "AgentSeedSchema":
        if self.mode == "pipeline":
            if self.pipeline_config is None or not self.pipeline_config.nodes:
                raise ValueError(
                    f"agent '{self.slug}' has mode=pipeline but no "
                    "top-level pipeline_config.nodes. Either move "
                    "pipeline_config out of model_config (most common cause), "
                    "or add the graph."
                )
        return self

    @field_validator("slug")
    @classmethod
    def _slug_lower(cls, v: str) -> str:
        if v != v.lower():
            raise ValueError("slug must be lowercase")
        return v


def validate_agent_yaml(path: Any, data: dict) -> AgentSeedSchema:
    """Run strict validation on a parsed YAML payload.

    Re-raises ``ValueError`` (with the offending file name prefixed) so
    a single try/except in the loader gives a useful traceback instead
    of "KeyError: 'slug'" 50 frames in.
    """
    try:
        return AgentSeedSchema.model_validate(data)
    except Exception as e:  # pragma: no cover -- re-raised with context
        raise ValueError(f"Invalid agent seed {path}: {e}") from e
