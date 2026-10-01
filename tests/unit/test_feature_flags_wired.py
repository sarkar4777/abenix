"""Every flag in ROLE_FEATURES has a consumer.

A flag is wired when a sidebar item declares it as `feature` or an API
module reads it outside the ROLE_FEATURES table itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core import permissions
from app.core.permissions import ROLE_FEATURES, features_for

ROOT = Path(__file__).resolve().parents[2]
SIDEBAR = ROOT / "apps" / "web" / "src" / "components" / "layout" / "Sidebar.tsx"
API_ROOT = ROOT / "apps" / "api" / "app"
PERMISSIONS_PY = Path(permissions.__file__)

ALL_FLAGS = sorted({k for role in ROLE_FEATURES.values() for k in role})


def _sidebar_features() -> set[str]:
    text = SIDEBAR.read_text(encoding="utf-8")
    return set(re.findall(r"feature:\s*'([a-z_]+)'", text))


def _permissions_without_table() -> str:
    text = PERMISSIONS_PY.read_text(encoding="utf-8")
    start = text.index("ROLE_FEATURES: dict")
    end = text.index("\n}\n", start) + 3
    return text[:start] + text[end:]


def _api_reads(flag: str) -> bool:
    needle = f'"{flag}"'
    if needle in _permissions_without_table():
        return True
    for path in API_ROOT.rglob("*.py"):
        if path == PERMISSIONS_PY:
            continue
        if needle in path.read_text(encoding="utf-8", errors="ignore"):
            return True
    return False


@pytest.mark.parametrize("flag", ALL_FLAGS)
def test_flag_has_a_consumer(flag):
    assert flag in _sidebar_features() or _api_reads(
        flag
    ), f"{flag} is set in ROLE_FEATURES but nothing reads it"


def test_sidebar_only_uses_known_flags():
    unknown = _sidebar_features() - set(ALL_FLAGS)
    assert not unknown, f"Sidebar declares flags missing from ROLE_FEATURES: {unknown}"


def test_review_queue_and_settings_are_admin_only_by_default():
    user = features_for(type("U", (), {"role": "user"})())
    creator = features_for(type("U", (), {"role": "creator"})())
    admin = features_for(type("U", (), {"role": "admin"})())
    for flag in ("review_queue", "manage_settings", "see_other_users_resources"):
        assert user[flag] is False and creator[flag] is False and admin[flag] is True
    assert user["use_meetings"] is True


def test_see_other_users_resources_drives_scope_helper():
    admin = type("U", (), {"role": "admin"})()
    member = type("U", (), {"role": "creator"})()
    assert permissions.sees_other_users_resources(admin) is True
    assert permissions.sees_other_users_resources(member) is False


def test_review_queue_sidebar_item_uses_flag_not_adminonly():
    text = SIDEBAR.read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if "/review-queue" in ln)
    assert "feature: 'review_queue'" in line
    assert "adminOnly" not in line
