"""Access rules for agents: who may read, run, publish and share.

Pure tests over the predicates the routers call. No database.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.core.permissions import (
    AGENT_VISIBILITIES,
    can_access_agent,
    can_publish_agent,
    is_platform_agent,
)
from app.services.agent_share import (
    PERMISSION_FROM_API,
    PUBLIC_CONFIG_KEYS,
    public_model_config,
    serialize_agent_share,
)
from app.services.share_export import (
    drop_unknown_refs,
    referenced_resource_ids,
    sanitize_for_export,
    strip_credentials,
)
from models.resource_share import SharePermission
from models.user import UserRole

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def _user(role=UserRole.USER, tenant=TENANT_A):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant, role=role, email="u@x.io")


def _agent(
    creator, *, tenant=TENANT_A, agent_type="custom", published=False, status="active"
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant,
        creator_id=creator.id if creator else None,
        agent_type=agent_type,
        is_published=published,
        status=status,
    )


# ── read / execute ────────────────────────────────────────────────────


def test_owner_can_view_and_execute():
    owner = _user()
    a = _agent(owner)
    assert can_access_agent(a, owner)
    assert can_access_agent(a, owner, permission_required=SharePermission.EXECUTE)


def test_tenant_member_without_share_is_denied():
    owner, other = _user(), _user()
    a = _agent(owner)
    assert not can_access_agent(a, other)
    assert not can_access_agent(a, other, permission_required=SharePermission.EXECUTE)


def test_admin_in_same_tenant_allowed_but_not_cross_tenant():
    owner = _user()
    admin_a = _user(UserRole.ADMIN)
    admin_b = _user(UserRole.ADMIN, tenant=TENANT_B)
    a = _agent(owner)
    assert can_access_agent(a, admin_a, permission_required=SharePermission.EXECUTE)
    assert not can_access_agent(a, admin_b)


def test_oob_agent_runnable_by_everyone_in_any_tenant():
    system = _user(UserRole.ADMIN)
    a = _agent(system, agent_type="oob")
    stranger = _user(tenant=TENANT_B)
    assert is_platform_agent(a)
    assert can_access_agent(a, stranger, permission_required=SharePermission.EXECUTE)


def test_null_creator_counts_as_platform_agent():
    a = _agent(None)
    assert is_platform_agent(a)
    assert can_access_agent(a, _user())


def test_view_share_allows_get_but_not_execute():
    owner, viewer = _user(), _user()
    a = _agent(owner)
    # accessible_ids is filtered by minimum permission before the call.
    assert can_access_agent(a, viewer, accessible_ids={a.id})
    assert not can_access_agent(
        a, viewer, accessible_ids=set(), permission_required=SharePermission.EXECUTE
    )


def test_execute_share_allows_execute():
    owner, runner = _user(), _user()
    a = _agent(owner)
    assert can_access_agent(
        a, runner, accessible_ids={a.id}, permission_required=SharePermission.EXECUTE
    )


def test_share_ids_do_not_cross_tenants():
    owner = _user()
    a = _agent(owner)
    outsider = _user(tenant=TENANT_B)
    assert not can_access_agent(a, outsider, accessible_ids={a.id})


def test_subscription_only_counts_for_published_active_agents():
    owner = _user()
    subscriber = _user(tenant=TENANT_B)
    published = _agent(owner, published=True)
    hidden = _agent(owner, published=False)
    pending = _agent(owner, published=True, status="pending_review")
    assert can_access_agent(published, subscriber, subscribed=True)
    assert can_access_agent(
        published,
        subscriber,
        subscribed=True,
        permission_required=SharePermission.EXECUTE,
    )
    assert not can_access_agent(
        published, subscriber, subscribed=True, permission_required=SharePermission.EDIT
    )
    assert not can_access_agent(hidden, subscriber, subscribed=True)
    assert not can_access_agent(pending, subscriber, subscribed=True)
    assert not can_access_agent(published, subscriber, subscribed=False)


# ── publish ───────────────────────────────────────────────────────────


def test_publish_visibility_must_be_known():
    owner = _user(UserRole.ADMIN)
    a = _agent(owner)
    ok, why = can_publish_agent(a, owner, "everyone")
    assert not ok and why.startswith("visibility")
    assert set(AGENT_VISIBILITIES) == {"tenant", "specific", "public"}


def test_publish_requires_owner_or_admin():
    owner, other, admin = _user(), _user(), _user(UserRole.ADMIN)
    a = _agent(owner)
    assert can_publish_agent(a, owner, "tenant")[0]
    assert can_publish_agent(a, admin, "specific")[0]
    assert not can_publish_agent(a, other, "tenant")[0]


def test_marketplace_publish_needs_feature():
    plain = _user(UserRole.USER)
    creator = _user(UserRole.CREATOR)
    admin = _user(UserRole.ADMIN)
    assert not can_publish_agent(_agent(plain), plain, "public")[0]
    assert can_publish_agent(_agent(creator), creator, "public")[0]
    assert can_publish_agent(_agent(admin), admin, "public")[0]


def test_publish_denied_across_tenants():
    owner = _user()
    admin_b = _user(UserRole.ADMIN, tenant=TENANT_B)
    assert not can_publish_agent(_agent(owner), admin_b, "tenant")[0]


# ── marketplace serialization ─────────────────────────────────────────


def test_public_model_config_is_an_allowlist():
    cfg = {
        "model": "claude-haiku-4-5-20251001",
        "temperature": 0.2,
        "tools": ["web_search", {"name": "code_asset"}],
        "tool_config": {"code_asset": {"parameter_defaults": {"code_asset_id": "x"}}},
        "mcp_extensions": [{"connection_id": "abc"}],
        "example_prompts": ["hi"],
        "input_variables": [{"name": "q", "description": "d", "default": "secret"}],
        "openai_api_key": "sk-live",
    }
    out = public_model_config(cfg)
    assert set(out) <= set(PUBLIC_CONFIG_KEYS)
    assert out["tools"] == ["web_search", "code_asset"]
    assert "tool_config" not in out and "mcp_extensions" not in out
    assert "openai_api_key" not in out
    assert out["input_variables"] == [{"name": "q", "description": "d"}]
    assert public_model_config(None) == {}


# ── share serialization ───────────────────────────────────────────────


def test_share_permission_round_trip():
    assert PERMISSION_FROM_API["view"] is SharePermission.VIEW
    assert PERMISSION_FROM_API["execute"] is SharePermission.EXECUTE
    assert PERMISSION_FROM_API["use"] is SharePermission.EXECUTE
    assert PERMISSION_FROM_API["edit"] is SharePermission.EDIT
    share = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        shared_with_email="v@x.io",
        shared_with_user_id=uuid.uuid4(),
        permission=SharePermission.EXECUTE,
        shared_by=uuid.uuid4(),
        created_at=None,
    )
    data = serialize_agent_share(share)
    assert data["permission"] == "execute"
    assert data["email"] == data["shared_with_email"] == "v@x.io"
    assert data["agent_id"] == str(share.resource_id)


# ── export / import scrubbing ─────────────────────────────────────────


def test_export_strips_credentials_and_resource_ids():
    kb = str(uuid.uuid4())
    cfg = {
        "model": "claude-haiku-4-5-20251001",
        "tools": ["knowledge_search", "api_connector"],
        "tool_config": {
            "api_connector": {
                "parameter_defaults": {
                    "connector_id": kb,
                    "api_key": "sk-abcdefgh12345678",
                },
                "usage_instructions": "call it",
            },
            "code_asset": {"parameter_defaults": {"code_asset_id": kb}},
        },
        "knowledge_collection_ids": [kb],
        "mcp_extensions": [{"connection_id": kb}],
        "headers": {"Authorization": "Bearer abc"},
        # built at run time so the publish leak scan does not read it as a real key
        "note": "sk-ant-" + "x" * 24,
    }
    clean, stripped = sanitize_for_export(cfg)
    assert clean["model"] == cfg["model"]
    assert clean["tools"] == cfg["tools"]
    tc = clean["tool_config"]["api_connector"]
    assert tc["usage_instructions"] == "call it"
    assert tc["parameter_defaults"] == {}
    assert clean["tool_config"]["code_asset"]["parameter_defaults"] == {}
    assert "knowledge_collection_ids" not in clean
    assert "mcp_extensions" not in clean
    assert clean["headers"] == {}
    assert "note" not in clean
    assert any("api_key" in s for s in stripped)
    assert any("connector_id" in s for s in stripped)
    # Source untouched.
    assert cfg["headers"]["Authorization"] == "Bearer abc"


def test_import_keeps_ids_in_tenant_and_drops_the_rest():
    mine, theirs = str(uuid.uuid4()), str(uuid.uuid4())
    cfg = {
        "tool_config": {
            "code_asset": {"parameter_defaults": {"code_asset_id": theirs}},
            "ml_model": {"parameter_defaults": {"model_id": mine}},
        },
        "knowledge_collection_ids": [mine, theirs],
        "mcp_extensions": [{"connection_id": mine}],
    }
    refs = referenced_resource_ids(cfg)
    assert refs == {
        "code_asset": {theirs},
        "ml_model": {mine},
        "knowledge_collection": {mine, theirs},
    }
    clean, dropped = drop_unknown_refs(cfg, {theirs})
    assert clean["tool_config"]["ml_model"]["parameter_defaults"]["model_id"] == mine
    assert (
        "code_asset_id" not in clean["tool_config"]["code_asset"]["parameter_defaults"]
    )
    assert clean["knowledge_collection_ids"] == [mine]
    assert "mcp_extensions" not in clean
    assert len(dropped) == 3


def test_import_drops_credential_keys_from_untrusted_template():
    cfg = {"model": "m", "tool_config": {"x": {"secret_token": "abc", "max_calls": 2}}}
    clean, stripped = strip_credentials(cfg)
    assert clean == {"model": "m", "tool_config": {"x": {"max_calls": 2}}}
    assert stripped == ["tool_config.x.secret_token"]


def test_non_uuid_ids_are_not_treated_as_references():
    cfg = {
        "tool_config": {
            "code_asset": {"parameter_defaults": {"code_asset_id": "my-slug"}}
        }
    }
    assert referenced_resource_ids(cfg) == {}
    clean, dropped = drop_unknown_refs(cfg, set())
    # A slug is not a tenant resource id we can verify, so it is dropped on import.
    assert (
        "code_asset_id" not in clean["tool_config"]["code_asset"]["parameter_defaults"]
    )
    assert dropped
