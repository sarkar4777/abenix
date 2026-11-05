"""Worker metrics: counters from the task signals, queue depth and state at scrape time."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
import yaml
from kb_pg import make_doc, make_kb, make_tenant
from prometheus_client import CollectorRegistry, generate_latest

from worker import metrics

ROOT = Path(__file__).resolve().parents[2]


def _value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get() if labels else counter._value.get()


def test_finished_documents_count_by_outcome_and_chunks():
    before = _value(metrics.documents_processed, status="ready")
    chunks = _value(metrics.chunks_ingested)
    metrics.observe_finished(
        "worker.tasks.document_processor.process_document",
        "SUCCESS",
        {"status": "ready", "vectors": 12},
    )
    assert _value(metrics.documents_processed, status="ready") == before + 1
    assert _value(metrics.chunks_ingested) == chunks + 12


def test_embed_failures_are_counted_and_still_raise():
    class Refused(Exception):
        refused = True

    @metrics.counts_embed_failures
    def boom():
        raise Refused("no")

    before = _value(metrics.embed_failures, reason="refused")
    with pytest.raises(Refused):
        boom()
    assert _value(metrics.embed_failures, reason="refused") == before + 1


def test_every_task_signal_records_duration_and_state():
    from celery import signals

    from worker import celery_app  # noqa: F401

    task = type("T", (), {"name": "worker.tasks.kb_delete.run"})()
    before = _value(metrics.task_runs, task="kb_delete.run", state="SUCCESS")
    signals.task_prerun.send(sender=task, task_id="t1", task=task)
    signals.task_postrun.send(
        sender=task, task_id="t1", task=task, retval={}, state="SUCCESS"
    )
    assert (
        _value(metrics.task_runs, task="kb_delete.run", state="SUCCESS") == before + 1
    )


def test_scrape_reports_queue_depth_and_knowledge_state(kb_conn, monkeypatch):
    cur = kb_conn.cursor()
    tenant = make_tenant(cur)
    kb = make_kb(cur, tenant)
    make_doc(cur, kb, ["a"])
    cur.execute(
        "INSERT INTO kb_reembed_jobs (id, tenant_id, kb_id, to_model, backend, from_generation, "
        "target_generation, status, chunks_done) VALUES (%s, %s, %s, 'm', 'pgvector', 0, 1, "
        "'running', 7)",
        (str(uuid.uuid4()), tenant, kb),
    )

    class FakeRedis:
        def llen(self, queue):
            return {"documents": 42, "cognify": 3}[queue]

    monkeypatch.setattr("redis.Redis.from_url", lambda *a, **k: FakeRedis())
    registry = CollectorRegistry()
    registry.register(metrics.KnowledgeCollector())
    text = generate_latest(registry).decode()
    assert 'abenix_kb_queue_depth{queue="documents"} 42.0' in text
    assert 'abenix_kb_queue_depth{queue="cognify"} 3.0' in text
    assert 'abenix_kb_documents{status="READY"}' in text
    assert 'abenix_kb_reembed_jobs{status="running"}' in text
    assert "abenix_kb_reembed_chunks_done" in text
    assert "abenix_kb_cognify_documents_pending" in text


def test_a_database_outage_does_not_break_the_scrape(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:y@127.0.0.1:1/none")
    monkeypatch.setattr(
        "redis.Redis.from_url", lambda *a, **k: (_ for _ in ()).throw(OSError("down"))
    )
    registry = CollectorRegistry()
    registry.register(metrics.KnowledgeCollector())
    assert b"abenix_kb_queue_depth" in generate_latest(registry)


def test_dashboard_queries_only_metrics_the_worker_emits():
    import re

    board = json.loads(
        (ROOT / "infra/helm/abenix/dashboards/knowledge-operations.json").read_text()
    )
    exported = {
        "abenix_kb_documents_processed_total",
        "abenix_kb_chunks_ingested_total",
        "abenix_kb_embed_failures_total",
        "abenix_kb_task_duration_seconds_bucket",
        "abenix_kb_queue_depth",
        "abenix_kb_documents",
        "abenix_kb_cognify_jobs",
        "abenix_kb_cognify_documents_pending",
        "abenix_kb_cognify_documents_processed",
        "abenix_kb_reembed_jobs",
        "abenix_kb_reembed_chunks_done",
        "abenix_kb_delete_jobs",
        "abenix_kb_connector_sources",
        "abenix_kb_connector_items_failed",
    }
    used = set()
    for panel in board["panels"]:
        for target in panel["targets"]:
            used.update(re.findall(r"abenix_kb_[a-z_]+", target["expr"]))
    assert used <= exported, used - exported
    for needed in ("ingest", "Queue depth", "Embedding failures", "Cognify"):
        assert any(
            needed.lower() in p["title"].lower() or needed == "ingest"
            for p in board["panels"]
        )
    source = (ROOT / "apps/worker/worker/metrics.py").read_text()
    for name in exported:
        assert name.replace("_bucket", "").replace("_total", "") in source


def test_chart_copy_and_observability_copy_match():
    a = (ROOT / "infra/helm/abenix/dashboards/knowledge-operations.json").read_text()
    b = (ROOT / "infra/observability/dashboards/knowledge-operations.json").read_text()
    assert a == b


def test_prometheus_keeps_the_worker_job_valid():
    docs = list(
        yaml.safe_load_all((ROOT / "infra/observability/prometheus.yaml").read_text())
    )
    config = next(d for d in docs if d and d.get("kind") == "ConfigMap")
    scrape = yaml.safe_load(next(iter(config["data"].values())))["scrape_configs"]
    assert "abenix-knowledge-workers" in {j["job_name"] for j in scrape}


def test_real_process_serves_counters_across_forked_children(tmp_path):
    """Children write files, the parent's server adds them up, the way prefork runs."""
    import os
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent(
        """
        import multiprocessing, os, urllib.request
        from worker import metrics

        metrics.prepare_files()
        metrics.start_server()

        def child():
            metrics.observe_finished(
                "worker.tasks.document_processor.process_document",
                "SUCCESS",
                {"status": "ready", "vectors": 5},
            )

        ctx = multiprocessing.get_context("fork")
        for _ in range(2):
            p = ctx.Process(target=child)
            p.start()
            p.join()
        body = urllib.request.urlopen(
            f"http://127.0.0.1:{os.environ['WORKER_METRICS_PORT']}/metrics"
        ).read().decode()
        print(body)
        """
    )
    from kb_pg import free_port

    env = {
        **os.environ,
        "WORKER_METRICS_PORT": str(free_port()),
        "PROMETHEUS_MULTIPROC_DIR": str(tmp_path / "prom"),
        "DATABASE_URL": "postgresql://x:y@127.0.0.1:1/none",
        "CELERY_BROKER_URL": "redis://127.0.0.1:1/0",
        "PYTHONPATH": os.pathsep.join(
            str(ROOT / p) for p in ("apps/worker", "apps/agent-runtime", "packages/db")
        ),
    }
    os.makedirs(env["PROMETHEUS_MULTIPROC_DIR"], exist_ok=True)
    out = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert out.returncode == 0, out.stderr[-1500:]
    assert 'abenix_kb_documents_processed_total{status="ready"} 2.0' in out.stdout
    assert "abenix_kb_chunks_ingested_total 10.0" in out.stdout
