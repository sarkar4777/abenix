"""Saudi Tourism Simulations — all scenarios run via Abenix agents."""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_utils import get_forge, parse_agent_json
from app.core.deps import get_db
from app.core.responses import error, success
from app.models.tourism_models import STSimulation, STUser, STDataset, SimulationType
from app.routers.auth import get_st_user

logger = logging.getLogger("sauditourism.simulations")
router = APIRouter(prefix="/api/st/simulations", tags=["st-simulations"])


SIMULATION_PRESETS = {
    "visa_policy": {
        "title": "Visa Fee Impact Analysis",
        "description": "Simulate visitor volume changes when visa fees are adjusted",
        "agent_instructions": "Use the scenario_planner tool with elasticity analysis to model visa fee impact on tourism demand.",
        "parameters": {
            "visa_fee_change_pct": {"type": "number", "default": -20, "min": -100, "max": 100, "label": "Visa Fee Change (%)"},
            "target_markets": {"type": "list", "default": ["UK", "Germany", "France", "China", "India"], "label": "Target Markets"},
            "time_horizon_months": {"type": "number", "default": 12, "min": 3, "max": 36, "label": "Time Horizon (months)"},
        },
    },
    "hotel_capacity": {
        "title": "Hotel Capacity Expansion",
        "description": "Simulate impact of adding hotel rooms in specific regions",
        "agent_instructions": "Use scenario_planner for capacity impact and financial_calculator for ROI, payback period, and NPV.",
        "parameters": {
            "region": {"type": "string", "default": "NEOM", "options": ["NEOM", "Riyadh", "Jeddah", "Al-Ula", "Asir"], "label": "Region"},
            "new_rooms": {"type": "number", "default": 5000, "min": 100, "max": 50000, "label": "New Rooms"},
            "star_rating": {"type": "number", "default": 5, "min": 3, "max": 5, "label": "Star Rating"},
            "avg_rate_sar": {"type": "number", "default": 1200, "min": 200, "max": 10000, "label": "Avg Nightly Rate (SAR)"},
        },
    },
    "seasonal_planning": {
        "title": "Seasonal Event Impact",
        "description": "Simulate visitor impact of Hajj/Umrah, Riyadh Season, Jeddah Season",
        "agent_instructions": "Use scenario_planner for event modeling and financial_calculator for ROI and economic multiplier analysis.",
        "parameters": {
            "event": {"type": "string", "default": "Riyadh Season", "options": ["Hajj", "Umrah Season", "Riyadh Season", "Jeddah Season", "AlUla Season"], "label": "Event"},
            "marketing_budget_sar": {"type": "number", "default": 500000000, "min": 0, "max": 5000000000, "label": "Marketing Budget (SAR)"},
            "duration_days": {"type": "number", "default": 90, "min": 7, "max": 180, "label": "Duration (days)"},
        },
    },
    "weather_impact": {
        "title": "Weather & Climate Impact",
        "description": "How does summer heat affect non-religious tourism?",
        "agent_instructions": "Use the weather_simulator tool to model climate conditions in KSA regions and scenario_planner to project tourism impact.",
        "parameters": {
            "scenario": {"type": "string", "default": "base", "options": ["base", "optimistic", "pessimistic", "extreme"], "label": "Climate Scenario"},
            "season": {"type": "string", "default": "summer", "options": ["spring", "summer", "autumn", "winter"], "label": "Season"},
            "region": {"type": "string", "default": "Riyadh", "options": ["Riyadh", "Jeddah", "NEOM", "Al-Ula", "Asir"], "label": "Region"},
        },
    },
    "competitor_analysis": {
        "title": "Competitor Market Response",
        "description": "What if UAE/Oman/Bahrain increase marketing spend?",
        "agent_instructions": "Use scenario_planner for competitive modeling and sentiment_analyzer for market perception impact.",
        "parameters": {
            "competitor": {"type": "string", "default": "UAE", "options": ["UAE", "Oman", "Bahrain", "Egypt", "Turkey"], "label": "Competitor"},
            "marketing_increase_pct": {"type": "number", "default": 30, "min": 0, "max": 200, "label": "Their Marketing Increase (%)"},
            "ksa_response": {"type": "string", "default": "match", "options": ["none", "match", "exceed"], "label": "KSA Response Strategy"},
        },
    },
}


def _build_data_context(datasets: list[STDataset], max_chars: int = 20000) -> str:
    parts = []
    char_count = 0
    for d in datasets:
        if not d.raw_text:
            continue
        section = f"\n=== DATASET: {d.title} (type={d.dataset_type.value if d.dataset_type else 'general'}) ===\n"
        section += d.raw_text[:10000]
        if char_count + len(section) > max_chars:
            break
        parts.append(section)
        char_count += len(section)
    return "".join(parts) if parts else "No uploaded data"


@router.get("/presets")
async def get_simulation_presets():
    # Strip agent_instructions from response
    clean = {k: {kk: vv for kk, vv in v.items() if kk != "agent_instructions"} for k, v in SIMULATION_PRESETS.items()}
    return success(clean)


@router.post("/run")
async def run_simulation(
    body: dict,
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    sim_type = body.get("type", "")
    params = body.get("parameters", {})

    if sim_type not in SIMULATION_PRESETS:
        return error(f"Unknown simulation type: {sim_type}. Valid: {list(SIMULATION_PRESETS.keys())}", 400)

    preset = SIMULATION_PRESETS[sim_type]

    # Gather user data for context
    datasets = (await db.execute(
        select(STDataset).where(STDataset.user_id == user.id)
    )).scalars().all()
    data_context = _build_data_context(datasets)

    forge, subject = get_forge(user)

    prompt = f"""Run a {preset['title']} simulation for Saudi Arabia tourism.

INSTRUCTIONS: {preset['agent_instructions']}

SIMULATION TYPE: {sim_type}
PARAMETERS: {json.dumps(params, indent=2)}

CONTEXT DATA FROM USER'S DATASETS:
{data_context}

IMPORTANT: You MUST use the available tools (scenario_planner, weather_simulator, financial_calculator, sentiment_analyzer) to perform the actual calculations. Do NOT make up numbers without using tools.

After running the simulation with tools, return ONLY a JSON object with:
{{
  "title": "{preset['title']}",
  "type": "{sim_type}",
  "summary": "<1-2 sentence executive summary>",
  "key_metrics": {{<metric_name>: <value>, ...}},
  "scenarios": [
    {{"label": "<scenario name>", "value": <projected value>, "description": "<explanation>"}},
    ...
  ],
  "recommendations": ["<recommendation 1>", "<recommendation 2>", ...],
  "methodology": "<brief description of tools and models used>"
}}"""

    result = await forge.execute("st-simulator", prompt, act_as=subject)
    parsed = parse_agent_json(result.output)

    sim = STSimulation(
        id=uuid.uuid4(),
        user_id=user.id,
        simulation_type=SimulationType(sim_type),
        title=preset["title"],
        parameters=params,
        results=parsed,
        status="completed",
    )
    db.add(sim)
    await db.commit()

    return success({
        "id": str(sim.id),
        "type": sim_type,
        "title": sim.title,
        "parameters": params,
        "results": parsed,
        "status": "completed",
        "agent_cost": result.cost,
        "agent_tokens": result.input_tokens + result.output_tokens,
    })


@router.get("")
async def list_simulations(
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(STSimulation).where(STSimulation.user_id == user.id).order_by(STSimulation.created_at.desc())
    )
    sims = result.scalars().all()
    return success([
        {
            "id": str(s.id),
            "type": s.simulation_type.value,
            "title": s.title,
            "parameters": s.parameters,
            "results": s.results,
            "status": s.status,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in sims
    ])


@router.get("/{sim_id}")
async def get_simulation(
    sim_id: str,
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(STSimulation).where(
            STSimulation.id == uuid.UUID(sim_id),
            STSimulation.user_id == user.id,
        )
    )
    s = result.scalar_one_or_none()
    if not s:
        return error("Simulation not found", 404)
    return success({
        "id": str(s.id),
        "type": s.simulation_type.value,
        "title": s.title,
        "parameters": s.parameters,
        "results": s.results,
        "status": s.status,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    })
