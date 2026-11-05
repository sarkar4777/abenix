"""Pools that cannot serve a run fail fast, runs nothing picks up fail plainly, dedicated mode creates real workers."""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from app.core import runtime_pools as rp

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "infra/helm/abenix"
helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    rp.reset_inventory()
    monkeypatch.setenv("DEDICATED_POOL_TEMPLATE", "abenix-agent-runtime-default")
    yield
    rp.reset_inventory()


def _inv(**pools):
    return {k.replace("_", "-"): v for k, v in pools.items()}


def _agent(**over):
    base = dict(
        id=uuid.uuid4(),
        runtime_pool="default",
        dedicated_mode=False,
        min_replicas=1,
        max_replicas=10,
        concurrency_per_replica=2,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_dedicated_agents_go_to_their_own_queue_and_others_to_their_pool():
    a = _agent(runtime_pool="chat")
    assert rp.effective_pool(a) == "chat"
    assert rp.effective_pool(_agent(runtime_pool=None)) == "default"
    b = _agent(dedicated_mode=True, runtime_pool="inline")
    assert rp.effective_pool(b) == f"dedicated-{b.id}"


@pytest.mark.asyncio
async def test_a_pool_that_is_not_deployed_is_refused_with_the_pools_that_are():
    with patch.object(
        rp, "_read_inventory", return_value=_inv(default=rp.PoolInfo("d", 1))
    ):
        msg = await rp.pool_problem("gpu")
    assert "'gpu' is not deployed" in msg
    assert "default" in msg


@pytest.mark.asyncio
async def test_a_pool_at_zero_that_will_wake_is_allowed_and_one_that_will_not_is_refused():
    pools = _inv(
        chat=rp.PoolInfo("c", 0, has_scaler=True),
        stuck=rp.PoolInfo("s", 0, has_scaler=False),
    )
    with patch.object(rp, "_read_inventory", return_value=pools):
        assert await rp.pool_problem("chat") is None
        assert "no autoscaler" in await rp.pool_problem("stuck")


@pytest.mark.asyncio
async def test_a_dedicated_pool_is_never_refused_while_it_comes_up():
    with patch.object(rp, "_read_inventory", return_value=_inv()):
        assert await rp.pool_problem("dedicated-abc") is None


@pytest.mark.asyncio
async def test_outside_a_cluster_nothing_is_refused(monkeypatch):
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    assert await rp.pool_problem("anything") is None


@pytest.mark.asyncio
async def test_a_pool_created_a_moment_ago_is_seen_despite_the_cache():
    first = _inv(default=rp.PoolInfo("d", 1))
    second = _inv(default=rp.PoolInfo("d", 1), chat=rp.PoolInfo("c", 1))
    reads = MagicMock(side_effect=[first, second])
    with patch.object(rp, "_read_inventory", reads):
        assert await rp.pool_problem("default") is None
        rp._cache = (rp._cache[0] - rp.MISS_RETRY_SECONDS - 1, rp._cache[1])
        assert await rp.pool_problem("chat") is None
    assert reads.call_count == 2


def test_code_runners_are_never_taken_for_runtime_pools(monkeypatch):
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    kube = SimpleNamespace(
        ns="abenix",
        apps=MagicMock(),
        scaled_objects=MagicMock(return_value=[]),
    )
    kube.apps.list_namespaced_deployment.return_value = SimpleNamespace(items=[])
    with patch.object(rp, "_Kube", return_value=kube):
        rp._read_inventory()
    selector = kube.apps.list_namespaced_deployment.call_args.kwargs["label_selector"]
    assert selector == "app.kubernetes.io/component=runtime-pool"
    assert "app!=abenix-code-runner" in kube.scaled_objects.call_args.args[0]


def _pool_template():
    return {
        "metadata": {
            "name": "abenix-agent-runtime-default",
            "uid": "tpl-uid",
            "labels": {
                "app.kubernetes.io/instance": "abenix",
                rp.POOL_LABEL: "default",
            },
        },
        "spec": {
            "template": {
                "metadata": {
                    "labels": {
                        "app.kubernetes.io/name": "agent-runtime",
                        rp.POOL_LABEL: "default",
                    },
                    "annotations": {
                        "prometheus.io/scrape": "true",
                        "kubectl.kubernetes.io/restartedAt": "now",
                    },
                },
                "spec": {
                    "containers": [
                        {
                            "name": "agent-runtime",
                            "image": "runtime:abc",
                            "env": [
                                {"name": "RUNTIME_POOL", "value": "default"},
                                {"name": "AGENT_CONCURRENCY", "value": "3"},
                                {"name": "NATS_URL", "value": "nats://x"},
                            ],
                        }
                    ]
                },
            }
        },
    }


def _scaler_template():
    return {
        "metadata": {"name": "t", "labels": {rp.POOL_LABEL: "default"}},
        "spec": {
            "scaleTargetRef": {"name": "abenix-agent-runtime-default"},
            "minReplicaCount": 1,
            "maxReplicaCount": 2,
            "cooldownPeriod": 30,
            "advanced": {"keep": "me"},
            "triggers": [
                {
                    "type": "nats-jetstream",
                    "metadata": {
                        "consumer": "abenix-default-consumer",
                        "stream": "agents",
                    },
                },
                {
                    "type": "prometheus",
                    "metadata": {"query": 'rate(x{pool="default"}[5m])'},
                },
            ],
        },
    }


def test_the_deployment_is_the_chart_pool_pointed_at_the_agents_queue():
    a = _agent(concurrency_per_replica=7, min_replicas=1, max_replicas=10)
    body = rp.build_deployment(_pool_template(), a, cap=3, has_scaler=True)
    key = f"dedicated-{a.id}"
    pod = body["spec"]["template"]
    env = {e["name"]: e["value"] for e in pod["spec"]["containers"][0]["env"]}
    assert env["RUNTIME_POOL"] == key
    assert env["AGENT_CONCURRENCY"] == "7"
    assert env["NATS_URL"] == "nats://x"
    assert pod["spec"]["containers"][0]["image"] == "runtime:abc"
    assert body["spec"]["selector"]["matchLabels"][rp.POOL_LABEL] == key
    assert pod["metadata"]["labels"][rp.POOL_LABEL] == key
    assert pod["metadata"]["labels"]["app.kubernetes.io/name"] == "agent-runtime"
    assert "kubectl.kubernetes.io/restartedAt" not in pod["metadata"]["annotations"]
    assert body["metadata"]["ownerReferences"][0]["uid"] == "tpl-uid"
    assert len(body["metadata"]["name"]) <= 63


def test_without_an_autoscaler_a_dedicated_pool_keeps_a_worker():
    a = _agent(min_replicas=0, max_replicas=2)
    assert (
        rp.build_deployment(_pool_template(), a, 3, has_scaler=True)["spec"]["replicas"]
        == 0
    )
    assert (
        rp.build_deployment(_pool_template(), a, 3, has_scaler=False)["spec"][
            "replicas"
        ]
        == 1
    )


def test_the_scaler_reads_the_agents_durable_with_the_template_cooldowns_and_the_cap():
    a = _agent(min_replicas=5, max_replicas=50)
    so = rp.build_scaler(_scaler_template(), a, 4, {"name": "n", "uid": "u"})
    key = f"dedicated-{a.id}"
    spec = so["spec"]
    assert spec["scaleTargetRef"] == {"name": rp.dedicated_name(a.id)}
    assert (spec["minReplicaCount"], spec["maxReplicaCount"]) == (4, 4)
    assert spec["cooldownPeriod"] == 30
    assert spec["advanced"] == {"keep": "me"}
    assert spec["triggers"][0]["metadata"]["consumer"] == f"abenix-{key}-consumer"
    assert [t["type"] for t in spec["triggers"]] == ["nats-jetstream"]
    assert so["metadata"]["ownerReferences"][0]["uid"] == "u"
    assert so["metadata"]["labels"][rp.POOL_LABEL] == key


class _Kube:
    ns = "abenix"

    def __init__(self, scaler=True, pools=0):
        self.dep = None
        self.so = None
        self.template_scaler = _scaler_template() if scaler else None
        self.pools = pools
        self.apps = MagicMock()
        self.custom = MagicMock()
        self.apps.read_namespaced_deployment.side_effect = self._read
        self.apps.create_namespaced_deployment.side_effect = self._create
        self.apps.list_namespaced_deployment.side_effect = (
            lambda *a, **k: SimpleNamespace(items=[object()] * self.pools)
        )
        self.custom.create_namespaced_custom_object.side_effect = self._so

    def _read(self, name, ns):
        from kubernetes.client.exceptions import ApiException

        if name == "abenix-agent-runtime-default":
            return "template"
        if self.dep is None:
            raise ApiException(status=404)
        return self.dep

    def _create(self, ns, body):
        self.dep = SimpleNamespace(
            metadata=SimpleNamespace(
                uid="dep-uid", annotations=body["metadata"]["annotations"]
            )
        )
        return self.dep

    def _so(self, group, version, ns, plural, body):
        self.so = body

    def serialize(self, obj):
        return _pool_template()

    def get_scaled_object(self, name):
        if name == "abenix-agent-runtime-default":
            return self.template_scaler
        return self.so


def test_turning_on_creates_the_deployment_and_scaler_and_a_second_pass_changes_nothing():
    pytest.importorskip("kubernetes")
    kube, a = _Kube(), _agent()
    assert rp._ensure_sync(a, kube) == "created"
    assert kube.so["spec"]["scaleTargetRef"]["name"] == rp.dedicated_name(a.id)
    kube.apps.reset_mock(return_value=False, side_effect=False)
    assert rp._ensure_sync(a, kube) == "updated"
    kube.apps.patch_namespaced_deployment.assert_not_called()
    kube.apps.create_namespaced_deployment.assert_not_called()


def test_a_new_runtime_image_reaches_the_dedicated_pool():
    kube, a = _Kube(), _agent()
    rp._ensure_sync(a, kube)
    newer = _pool_template()
    newer["spec"]["template"]["spec"]["containers"][0]["image"] = "runtime:new"
    kube.serialize = lambda obj: newer
    rp._ensure_sync(a, kube)
    patch_body = kube.apps.patch_namespaced_deployment.call_args.args[2]
    image = patch_body["spec"]["template"]["spec"]["containers"][0]["image"]
    assert image == "runtime:new"


def test_the_limit_on_dedicated_pools_is_enforced(monkeypatch):
    monkeypatch.setenv("DEDICATED_POOL_MAX_POOLS", "2")
    with pytest.raises(RuntimeError, match="limit"):
        rp._ensure_sync(_agent(), _Kube(pools=2))


def test_half_a_pool_is_taken_back_when_the_scaler_cannot_be_created():
    kube, a = _Kube(), _agent()
    kube.custom.create_namespaced_custom_object.side_effect = RuntimeError("forbidden")
    with pytest.raises(RuntimeError):
        rp._ensure_sync(a, kube)
    kube.apps.delete_namespaced_deployment.assert_called_once()


def test_no_keda_means_a_plain_deployment_and_no_scaler():
    kube, a = _Kube(scaler=False), _agent(min_replicas=0)
    rp._ensure_sync(a, kube)
    assert kube.so is None
    body = kube.apps.create_namespaced_deployment.call_args.args[1]
    assert body["spec"]["replicas"] == 1


@pytest.mark.asyncio
async def test_retire_waits_for_queued_runs_then_removes_everything():
    backend = SimpleNamespace(
        backlog=AsyncMock(side_effect=[2, 0]), remove_queue=AsyncMock()
    )
    with patch.object(rp, "_queue_backend", return_value=backend), patch.object(
        rp, "_delete_sync"
    ) as delete:
        assert await rp.retire("a1") == "draining"
        delete.assert_not_called()
        backend.remove_queue.assert_not_called()
        assert await rp.retire("a1") == "removed"
    delete.assert_called_once()
    backend.remove_queue.assert_awaited_once_with("dedicated-a1")


class _Scalars:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


@pytest.mark.asyncio
async def test_reconcile_makes_durables_and_pools_and_removes_orphans():
    live = _agent(dedicated_mode=True)
    orphan = f"dedicated-{uuid.uuid4()}"
    pools = {"default": rp.PoolInfo("d", 1), orphan: rp.PoolInfo("o", 0, True)}
    backend = SimpleNamespace(ensure_consumer=AsyncMock())
    db = MagicMock()
    db.execute = AsyncMock(return_value=_Scalars([live]))

    @asynccontextmanager
    async def session():
        yield db

    with patch.object(rp, "_read_inventory", return_value=pools), patch.object(
        rp, "_queue_backend", return_value=backend
    ), patch.object(rp, "in_cluster", return_value=True), patch.object(
        rp, "provision", AsyncMock(return_value="created")
    ) as provision, patch.object(
        rp, "retire", AsyncMock(return_value="removed")
    ) as retire, patch(
        "app.core.deps.async_session", session
    ):
        out = await rp.reconcile()
    assert {c.args[0] for c in backend.ensure_consumer.await_args_list} == set(pools)
    provision.assert_awaited_once_with(live)
    retire.assert_awaited_once_with(orphan[len("dedicated-") :])
    assert out == {"created": 1, "removed": 1}


def _db_with(agent):
    result = MagicMock()
    result.scalar_one_or_none.return_value = agent
    return SimpleNamespace(
        execute=AsyncMock(return_value=result),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )


def _scale_agent(**over):
    return SimpleNamespace(
        name="a",
        slug="a",
        category="c",
        status="active",
        agent_type="custom",
        rate_limit_qps=None,
        daily_budget_usd=None,
        daily_cost_limit=None,
        model_config_={},
        **{k: v for k, v in vars(_agent(**over)).items()},
    )


def _admin():
    return SimpleNamespace(role="admin", email="a@x", tenant_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_dedicated_on_creates_the_pool_before_routing_to_it():
    from app.routers import admin_scaling as ads

    agent = _scale_agent()
    db = _db_with(agent)
    with patch.object(rp, "in_cluster", return_value=True), patch.object(
        rp, "provision", AsyncMock(return_value="created")
    ) as provision, patch("app.core.config.settings.scaling_exec_remote", True):
        resp = await ads.set_dedicated_mode(
            str(agent.id), {"enabled": True}, user=_admin(), db=db
        )
    assert resp.status_code == 200
    provision.assert_awaited_once()
    assert agent.dedicated_mode is True
    body = json.loads(resp.body)["data"]
    assert body["effective_pool"] == f"dedicated-{agent.id}"
    assert body["dedicated_state"] == "created"


@pytest.mark.asyncio
async def test_dedicated_on_that_cannot_be_provisioned_stays_shared_and_says_why():
    from app.routers import admin_scaling as ads

    agent = _scale_agent()
    with patch.object(rp, "in_cluster", return_value=True), patch.object(
        rp, "provision", AsyncMock(side_effect=RuntimeError("forbidden"))
    ), patch("app.core.config.settings.scaling_exec_remote", True):
        resp = await ads.set_dedicated_mode(
            str(agent.id), {"enabled": True}, user=_admin(), db=_db_with(agent)
        )
    assert resp.status_code == 502
    assert agent.dedicated_mode is False
    assert "forbidden" in json.loads(resp.body)["error"]["message"]


@pytest.mark.asyncio
async def test_dedicated_on_is_refused_when_the_cluster_cannot_do_it(monkeypatch):
    from app.routers import admin_scaling as ads

    monkeypatch.delenv("DEDICATED_POOL_TEMPLATE")
    agent = _scale_agent()
    resp = await ads.set_dedicated_mode(
        str(agent.id), {"enabled": True}, user=_admin(), db=_db_with(agent)
    )
    assert resp.status_code == 409
    assert agent.dedicated_mode is False


@pytest.mark.asyncio
async def test_dedicated_off_routes_back_first_and_then_retires_the_pool():
    from app.routers import admin_scaling as ads

    agent = _scale_agent(dedicated_mode=True)
    seen = {}

    async def retire(agent_id):
        seen["flag_at_retire"] = agent.dedicated_mode
        return "draining"

    with patch.object(rp, "in_cluster", return_value=True), patch.object(
        rp, "retire", retire
    ):
        resp = await ads.set_dedicated_mode(
            str(agent.id), {"enabled": False}, user=_admin(), db=_db_with(agent)
        )
    assert seen["flag_at_retire"] is False
    assert json.loads(resp.body)["data"]["dedicated_state"] == "draining"


@pytest.mark.asyncio
async def test_the_admin_api_will_not_move_an_agent_to_a_pool_that_is_not_there():
    from app.routers import admin_scaling as ads

    agent = _scale_agent()
    with patch.object(
        rp, "_read_inventory", return_value=_inv(default=rp.PoolInfo("d", 1))
    ):
        resp = await ads.update_agent_scale(
            str(agent.id), {"runtime_pool": "gpu"}, user=_admin(), db=_db_with(agent)
        )
    assert resp.status_code == 400
    assert json.loads(resp.body)["error"]["error_code"] == rp.POOL_NOT_DEPLOYED
    assert agent.runtime_pool == "default"


@pytest.mark.asyncio
async def test_a_trigger_to_a_missing_pool_fails_at_once_and_is_never_published():
    from app.routers import triggers
    from models.execution import Execution, ExecutionStatus

    agent = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="a",
        status="active",
        model_config_={},
        runtime_pool="gpu",
        dedicated_mode=False,
        daily_cost_limit=None,
        daily_budget_usd=None,
    )
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=agent.tenant_id)
    ex = Execution(
        id=uuid.uuid4(),
        tenant_id=agent.tenant_id,
        agent_id=agent.id,
        user_id=user.id,
        input_message="m",
        status=ExecutionStatus.RUNNING,
    )
    backend = SimpleNamespace(submit=AsyncMock())
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock(), add=MagicMock())
    with patch("app.core.config.settings.scaling_exec_remote", True), patch(
        "engine.queue_backend.get_queue_backend", return_value=backend
    ), patch.object(rp, "pool_problem", AsyncMock(return_value="not there")), patch(
        "engine.agent_budget.check_agent_budget", AsyncMock(return_value=None)
    ):
        result, dispatched = await triggers.dispatch_execution(
            db, agent=agent, user=user, message="m", context={}, execution=ex
        )
    assert dispatched is False
    assert result.status == ExecutionStatus.FAILED
    assert result.failure_code == rp.POOL_NOT_DEPLOYED
    backend.submit.assert_not_awaited()


def test_failure_codes_classify_the_new_messages():
    from app.core.failure_codes import classify_exception

    assert (
        classify_exception(RuntimeError(rp.not_picked_up_message("gpu", 10)))
        == rp.QUEUE_NOT_PICKED_UP
    )


class _SweepDb:
    def __init__(self, rows):
        self.rows = rows
        self.updates: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        from sqlalchemy.dialects import postgresql

        compiled = stmt.compile(dialect=postgresql.dialect())
        if str(compiled).startswith("UPDATE"):
            self.updates.append(compiled.params)
            return SimpleNamespace(all=lambda: [])
        return SimpleNamespace(all=lambda: self.rows)

    async def commit(self):
        pass

    def add(self, obj):
        pass


@pytest.mark.asyncio
async def test_a_queued_run_no_worker_ever_took_fails_saying_so_and_tells_waiting_clients():
    from app.core import scheduler

    now = datetime.now(timezone.utc)
    queued, inline_run, ded_agent, ded = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    old = now - timedelta(minutes=30)
    rows = [
        (queued, None, uuid.uuid4(), uuid.uuid4(), old, None, None, 0, "gpu", False),
        (
            inline_run,
            None,
            uuid.uuid4(),
            uuid.uuid4(),
            old,
            None,
            None,
            0,
            "inline",
            False,
        ),
        (ded, None, uuid.uuid4(), ded_agent, old, None, None, 0, "default", True),
    ]
    db = _SweepDb(rows)

    @asynccontextmanager
    async def lock(key):
        yield True

    async def waiting(ids):
        return set()

    published = AsyncMock()
    with patch.object(scheduler, "advisory_lock", lock), patch(
        "app.core.deps.async_session", lambda: db
    ), patch("app.core.hitl.waiting_execution_ids", waiting), patch(
        "app.core.config.settings.scaling_exec_remote", True
    ), patch(
        "app.core.execution_bus.publish_event", published
    ):
        out = await scheduler.sweep_stale_executions()
    assert out == {"swept": 3}
    queued_updates = [
        u for u in db.updates if u.get("failure_code") == rp.QUEUE_NOT_PICKED_UP
    ]
    assert len(queued_updates) == 2
    assert any("pool 'gpu'" in u["error_message"] for u in queued_updates)
    assert any(f"dedicated-{ded_agent}" in u["error_message"] for u in queued_updates)
    stale = next(u for u in db.updates if u.get("failure_code") == "STALE_SWEEP")
    assert inline_run in stale["id_1"]
    assert {c.args[0] for c in published.await_args_list} == {str(queued), str(ded)}


def test_a_claimed_or_inline_run_is_not_called_unclaimed():
    from app.core import scheduler

    row = lambda runner, attempts, pool, ded=False: (  # noqa: E731
        1,
        2,
        3,
        "agent",
        None,
        runner,
        None,
        attempts,
        pool,
        ded,
    )
    assert scheduler.queued_pool(row(None, 0, "chat"), True) == "chat"
    assert scheduler.queued_pool(row(None, 0, None), True) == "default"
    assert scheduler.queued_pool(row("rt-1", 1, "chat"), True) is None
    assert scheduler.queued_pool(row(None, 1, "chat"), True) is None
    assert scheduler.queued_pool(row(None, 0, "inline"), True) is None
    assert scheduler.queued_pool(row(None, 0, "chat"), False) is None
    assert (
        scheduler.queued_pool(row(None, 0, "inline", True), True) == "dedicated-agent"
    )


def _render(*values, sets=()):
    cmd = ["helm", "template", "abenix", str(CHART), "--namespace", "abenix"]
    for v in values:
        cmd += ["-f", str(CHART / v)]
    for s in sets:
        cmd += ["--set", s]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def _find(docs, kind, name):
    return next(d for d in docs if d["kind"] == kind and d["metadata"]["name"] == name)


@helm
def test_chart_defaults_keep_the_production_scale_down_timing():
    docs = _render("values-azure.yaml")
    so = _find(docs, "ScaledObject", "abenix-agent-runtime-default")
    assert so["spec"]["pollingInterval"] == 15
    assert so["spec"]["cooldownPeriod"] == 300
    down = so["spec"]["advanced"]["horizontalPodAutoscalerConfig"]["behavior"][
        "scaleDown"
    ]
    assert down["stabilizationWindowSeconds"] == 600
    assert down["policies"][0]["periodSeconds"] == 300


@helm
def test_the_api_may_create_dedicated_pools_only_when_they_are_on():
    docs = _render("values-local.yaml")
    role = _find(docs, "Role", "abenix-runtime-pools")
    rules = {r["resources"][0]: r["verbs"] for r in role["rules"]}
    assert "create" in rules["deployments"]
    assert "create" in rules["scaledobjects"]
    binding = _find(docs, "RoleBinding", "abenix-runtime-pools")
    assert binding["subjects"][0]["name"] == "default"
    config = _find(docs, "ConfigMap", "abenix-config")["data"]
    assert config["DEDICATED_POOL_TEMPLATE"] == "abenix-agent-runtime-default"

    off = _render("values-local.yaml", sets=["scaling.dedicated.enabled=false"])
    rules = {
        r["resources"][0]: r["verbs"]
        for r in _find(off, "Role", "abenix-runtime-pools")["rules"]
    }
    assert rules["deployments"] == ["get", "list"]
    assert (
        "DEDICATED_POOL_TEMPLATE"
        not in _find(off, "ConfigMap", "abenix-config")["data"]
    )


@helm
def test_pool_env_reaches_every_pool_pod():
    docs = _render("values-local.yaml", sets=["scaling.poolEnv.ABENIX_LLM_STUB=1"])
    dep = _find(docs, "Deployment", "abenix-agent-runtime-default")
    env = {
        e["name"]: e.get("value")
        for e in dep["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert env["ABENIX_LLM_STUB"] == "1"
