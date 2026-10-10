"""The model a new agent starts on, shared by the builder, the AI Builder and POST /api/agents."""

from __future__ import annotations

from typing import Any

# Balanced tier, best first. Never an Opus class or flagship model.
BALANCED_MODELS: tuple[str, ...] = (
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5-20250929",
    "claude-sonnet-4-20250514",
    "gpt-4.1",
    "gpt-4o",
    "azure-gpt-4.1",
    "azure-gpt-4o",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
)

# Used only when the catalogue cannot be read at all.
FALLBACK_MODEL = "claude-sonnet-4-5-20250929"

_KEY_PROVIDERS = ("anthropic", "openai", "google", "azure")


def _usable(m: dict[str, Any]) -> bool:
    if m.get("is_deprecated"):
        return False
    if (m.get("status") or "available") == "unavailable":
        return False
    return bool(m.get("provider_available", True) or m.get("subscription_served"))


def pick_default_model(
    models: list[dict[str, Any]],
    providers: dict[str, dict[str, Any]],
    subscription: dict[str, Any] | None,
) -> str:
    """Pick the default for a new agent from the live catalogue.

    `models` are /api/llm-models rows, `providers` the available-providers map and
    `subscription` the shape `subscription_state()` feeds the pickers.
    """
    sub = subscription or {}
    sub_model = str(sub.get("default_model") or "").strip()
    key_configured = any(
        (providers.get(p) or {}).get("configured") for p in _KEY_PROVIDERS
    )
    # exclusive mode runs every call on the subscription model anyway
    if sub.get("active") and sub_model and (sub.get("exclusive") or not key_configured):
        return sub_model

    usable = [m for m in models if m.get("value") and _usable(m)]
    by_id = {m["value"]: m for m in usable}
    for model_id in BALANCED_MODELS:
        if model_id in by_id:
            return model_id
    sonnets = sorted(
        (m["value"] for m in usable if "sonnet" in m["value"].lower()), reverse=True
    )
    if sonnets:
        return sonnets[0]
    if usable:
        # middle of the price range, never the priciest unless it is the only one
        ranked = sorted(usable, key=lambda m: float(m.get("output_per_m") or 0))
        return ranked[(len(ranked) - 1) // 2]["value"]
    if sub.get("active") and sub_model:
        return sub_model
    return FALLBACK_MODEL
