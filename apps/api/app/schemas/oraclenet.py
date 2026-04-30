"""OracleNet decision analysis schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any


class AnalyzeRequest(BaseModel):
    """Input for OracleNet decision analysis."""
    decision_prompt: str = Field(..., min_length=20, max_length=10000, description="The decision to analyze")
    context: dict[str, Any] = Field(default_factory=dict, description="Additional context: company info, constraints")
    depth: str = Field(default="standard", description="Analysis depth: quick, standard, deep")
    model: str | None = Field(default=None, description="Override model for synthesis")


class HistoricalAnalogy(BaseModel):
    title: str
    year: int | None = None
    relevance_score: float = 0.0
    context: str = ""
    decision_made: str = ""
    outcome: str = ""
    lessons: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class StakeholderImpact(BaseModel):
    stakeholder: str
    sentiment: str = "neutral"
    intensity: float = 0.5
    likely_actions: list[str] = Field(default_factory=list)
    timeline: str = ""
    evidence: str = ""


class Scenario(BaseModel):
    name: str
    probability: float = 0.0
    description: str = ""
    key_drivers: list[str] = Field(default_factory=list)
    timeline: str = ""
    signals_to_watch: list[str] = Field(default_factory=list)


class CascadeEffect(BaseModel):
    trigger: str
    effect: str
    order: int = 1
    probability: float = 0.0
    severity: str = "medium"
    affected_parties: list[str] = Field(default_factory=list)
    reversible: bool = True


class ContrarianPoint(BaseModel):
    argument: str
    evidence: str = ""
    severity: str = "moderate"
    probability: float = 0.0
    mitigation: str | None = None
    verdict: str = "proceed_with_caution"


class Recommendation(BaseModel):
    action: str
    timing: str = ""
    confidence: float = 0.0
    conditions: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)


class DecisionBrief(BaseModel):
    """Complete OracleNet decision analysis output."""
    executive_summary: str = ""
    parsed_decision: dict[str, Any] = Field(default_factory=dict)
    historical_analogies: list[HistoricalAnalogy] = Field(default_factory=list)
    current_state: dict[str, Any] = Field(default_factory=dict)
    stakeholder_impacts: list[StakeholderImpact] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)
    cascade_effects: list[CascadeEffect] = Field(default_factory=list)
    contrarian_analysis: list[ContrarianPoint] = Field(default_factory=list)
    recommendation: Recommendation | None = None
    monitoring_triggers: list[str] = Field(default_factory=list)
    key_assumptions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BriefListItem(BaseModel):
    """Summary item for listing past analyses."""
    execution_id: str
    decision_prompt: str
    status: str
    confidence: float | None = None
    created_at: str | None = None
    duration_ms: int | None = None
    cost: float | None = None
