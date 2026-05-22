"""Legacy adapter shim.

Adapter classes used to live here — one Python class per metals/gas
source. They have been deleted: their behaviour is now expressed as
named *presets* over the generic ``yahoo_finance`` abenix tool. Look in
``apps/api/app/core/seed_tool_presets.py`` for the equivalent rows.

This file stays so that legacy ``from app.market_data import adapters``
imports still succeed during the migration window. ``register_all()`` is
a no-op — registration happens on the abenix side at startup.
"""


def register_all() -> None:
    """No-op. Kept so legacy imports don't break."""
    return None
