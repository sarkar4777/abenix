"""ContractIQ-shaped portfolio-schema starter templates.

The generic Abenix router at /api/portfolio-schemas/templates/list carries
domain-neutral starters (real estate, M&A, ...). The energy-contracts
starter references the contractiq_* tables that only this app provisions,
so it lives here and the Portfolio Schemas UI is expected to union both
lists.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/contractiq/portfolio-schemas", tags=["contractiq-portfolio-schemas"])


@router.get("/templates/list")
async def list_templates() -> JSONResponse:
    """Return ContractIQ-shaped starter schemas."""
    return JSONResponse({"data": [
        {
            "id": "energy_contracts",
            "label": "Energy Contracts (PPA, Gas, Tolling)",
            "description": "Energy market contracts with clauses, risks, assets, events, and extracted commercial/technical data",
            "schema_json": {
                "domain": {
                    "name": "energy_contracts",
                    "label": "Energy Contract Portfolio",
                    "description": (
                        "Energy contract intelligence covering PPAs (solar, wind, hydro), "
                        "gas supply agreements, tolling contracts, and virtual PPAs."
                    ),
                    "record_noun": "contract",
                    "record_noun_plural": "contracts",
                },
                "main_table": {
                    "name": "contractiq_contracts",
                    "primary_key": "id",
                    "user_scope_column": "user_id",
                    "title_column": "title",
                    "type_column": "contract_type",
                    "status_column": "status",
                    "created_at_column": "created_at",
                    "search_columns": ["title", "counterparty_a", "counterparty_b"],
                    "list_columns": [
                        "id",
                        "title",
                        "contract_type",
                        "status",
                        "counterparty_a",
                        "counterparty_b",
                        "risk_score",
                        "total_capacity_mw",
                        "contract_value",
                        "currency",
                        "effective_date",
                        "expiry_date",
                    ],
                    "columns": {
                        "id": {"type": "uuid", "label": "ID"},
                        "title": {"type": "string", "label": "Title"},
                        "contract_type": {"type": "string", "label": "Type"},
                        "status": {"type": "string", "label": "Status"},
                        "counterparty_a": {
                            "type": "string",
                            "label": "Party A (Buyer)",
                        },
                        "counterparty_b": {
                            "type": "string",
                            "label": "Party B (Seller)",
                        },
                        "risk_score": {
                            "type": "number",
                            "label": "Risk Score",
                            "format": "{:.0f}/100",
                        },
                        "total_capacity_mw": {
                            "type": "number",
                            "label": "Capacity",
                            "format": "{:.0f} MW",
                        },
                        "contract_value": {
                            "type": "number",
                            "label": "Contract Value",
                            "format": "{:,.0f}",
                        },
                        "currency": {"type": "string", "label": "Currency"},
                        "effective_date": {
                            "type": "date",
                            "label": "Effective Date",
                        },
                        "expiry_date": {"type": "date", "label": "Expiry Date"},
                    },
                    "summary_aggregations": {
                        "total": {"sql": "count(*)", "label": "Total contracts"},
                        "avg_risk": {
                            "sql": "avg(risk_score)",
                            "label": "Average risk",
                            "format": "{:.1f}/100",
                        },
                        "total_value": {
                            "sql": "sum(contract_value)",
                            "label": "Total portfolio value",
                            "format": "{:,.0f}",
                        },
                        "total_mw": {
                            "sql": "sum(total_capacity_mw)",
                            "label": "Total capacity",
                            "format": "{:.0f} MW",
                        },
                    },
                },
                "related_tables": [
                    {
                        "name": "contractiq_clauses",
                        "relation": "one_to_many",
                        "foreign_key": "contract_id",
                        "label": "Clauses",
                        "searchable_columns": ["clause_title", "clause_text"],
                        "type_column": "clause_type",
                        "columns": {
                            "clause_number": {"type": "string", "label": "Number"},
                            "clause_title": {"type": "string", "label": "Title"},
                            "clause_type": {"type": "string", "label": "Type"},
                            "clause_text": {
                                "type": "text",
                                "label": "Text",
                                "truncate": 300,
                            },
                            "risk_level": {"type": "string", "label": "Risk Level"},
                            "risk_notes": {
                                "type": "text",
                                "label": "Risk Notes",
                                "truncate": 200,
                            },
                        },
                        "order_by": "clause_number",
                    },
                    {
                        "name": "contractiq_risk_analyses",
                        "relation": "one_to_many",
                        "foreign_key": "contract_id",
                        "label": "Risk Analyses",
                        "columns": {
                            "risk_category": {
                                "type": "string",
                                "label": "Category",
                            },
                            "risk_score": {
                                "type": "number",
                                "label": "Score",
                                "format": "{:.0f}/100",
                            },
                            "risk_description": {
                                "type": "text",
                                "label": "Description",
                                "truncate": 200,
                            },
                            "mitigation_suggestion": {
                                "type": "text",
                                "label": "Mitigation",
                                "truncate": 200,
                            },
                        },
                        "order_by": "risk_score DESC",
                    },
                    {
                        "name": "contractiq_assets",
                        "relation": "one_to_many",
                        "foreign_key": "contract_id",
                        "label": "Assets",
                        "columns": {
                            "asset_name": {"type": "string", "label": "Name"},
                            "asset_type": {"type": "string", "label": "Type"},
                            "capacity_mw": {
                                "type": "number",
                                "label": "Capacity (MW)",
                            },
                            "location": {"type": "string", "label": "Location"},
                            "technology": {"type": "string", "label": "Technology"},
                        },
                    },
                    {
                        "name": "contractiq_events",
                        "relation": "one_to_many",
                        "foreign_key": "contract_id",
                        "label": "Events",
                        "columns": {
                            "event_type": {"type": "string", "label": "Type"},
                            "event_date": {"type": "date", "label": "Date"},
                            "description": {
                                "type": "text",
                                "label": "Description",
                                "truncate": 150,
                            },
                            "status": {"type": "string", "label": "Status"},
                        },
                        "order_by": "event_date",
                    },
                    {
                        "name": "contractiq_extracted_data",
                        "relation": "one_to_many",
                        "foreign_key": "contract_id",
                        "label": "Extracted Data",
                        "is_kv_store": True,
                        "key_column": "field_name",
                        "value_column": "field_value",
                        "section_column": "section",
                        "type_column": "field_type",
                        "confidence_column": "confidence_score",
                        "columns": {
                            "section": {"type": "string", "label": "Section"},
                            "field_name": {"type": "string", "label": "Field"},
                            "field_value": {"type": "text", "label": "Value"},
                            "field_type": {"type": "string", "label": "Type"},
                            "confidence_score": {
                                "type": "number",
                                "label": "Confidence",
                                "format": "{:.0%}",
                            },
                        },
                    },
                ],
            },
        },
    ], "error": None})
