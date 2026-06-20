"""ContractIQ-shaped subject-policy templates.

The generic Abenix router at /api/access-control/templates only carries
templates that aren't tied to a specific app. ContractIQ-shaped templates
(subject_type='contractiq', CIQ data scopes, CIQ agent slugs) live here
and the policy-creation UI is expected to union both lists.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/contractiq/access-control", tags=["contractiq-access-control"])


@router.get("/templates")
async def list_policy_templates() -> JSONResponse:
    """Return ContractIQ-specific subject-policy templates."""
    templates = [
        {
            "id": "contractiq_user_isolated",
            "name": "ContractIQ User-Isolated",
            "description": "Each ContractIQ user can only access their own contracts and KB namespace",
            "subject_type": "contractiq",
            "rules": {
                "agents": {
                    "mode": "allowlist",
                    "slugs": ["contractiq-chat", "contractiq-pipeline"],
                },
                "knowledge_bases": [
                    {
                        "kb_id": "*",
                        "access_mode": "namespace",
                        "namespace_pattern": "contractiq-{subject_id}",
                        "allowed_actions": ["read", "search"],
                    }
                ],
                "data_scopes": {
                    "contractiq.contracts.user_id": "{subject_id}",
                },
                "denied_actions": ["delete", "admin"],
            },
        },
        {
            "id": "team_lead_cross_user",
            "name": "Team Lead (Cross-User Read)",
            "description": "Team lead can read contracts from team members",
            "subject_type": "contractiq",
            "rules": {
                "agents": {"mode": "allowlist", "slugs": ["contractiq-chat"]},
                "knowledge_bases": [
                    {
                        "kb_id": "*",
                        "access_mode": "namespace",
                        "namespace_pattern": "contractiq-team-{subject_id}",
                        "allowed_actions": ["read", "search"],
                    }
                ],
                "denied_actions": ["delete"],
            },
        },
    ]
    return JSONResponse({"data": templates, "error": None})
