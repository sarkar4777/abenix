"""Prometheus metrics for the knowledge worker.

Tasks run in forked children, so counters use the multiprocess files and one
HTTP server in the parent adds them up. WORKER_METRICS_PORT turns it on, which
has to happen before prometheus_client is imported.
"""

from __future__ import annotations

import functools
import logging
import os
import shutil
import tempfile
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

PORT = os.environ.get("WORKER_METRICS_PORT", "").strip()
_DIR = os.path.join(tempfile.gettempdir(), "abenix-worker-metrics")

if PORT:
    os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", _DIR)
    os.makedirs(os.environ["PROMETHEUS_MULTIPROC_DIR"], exist_ok=True)

from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
)  # noqa: E402
from prometheus_client.core import GaugeMetricFamily  # noqa: E402


def _metric(
    cls: Any, name: str, doc: str, labels: Iterable[str] = (), **kw: Any
) -> Any:
    existing = getattr(REGISTRY, "_names_to_collectors", {}).get(name)
    return existing if existing is not None else cls(name, doc, list(labels), **kw)


documents_processed = _metric(
    Counter,
    "abenix_kb_documents_processed_total",
    "Documents the ingest pipeline finished, by outcome",
    ["status"],
)
chunks_ingested = _metric(
    Counter, "abenix_kb_chunks_ingested_total", "Chunks written by the ingest pipeline"
)
embed_failures = _metric(
    Counter,
    "abenix_kb_embed_failures_total",
    "Embedding provider calls that failed",
    ["reason"],
)
task_runs = _metric(
    Counter,
    "abenix_kb_task_runs_total",
    "Knowledge worker tasks, by task and final state",
    ["task", "state"],
)
task_seconds = _metric(
    Histogram,
    "abenix_kb_task_duration_seconds",
    "How long a knowledge worker task took",
    ["task"],
    buckets=(0.5, 1, 5, 15, 60, 300, 900, 1800, 3600),
)


def counts_embed_failures(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            refused = getattr(e, "refused", None)
            reason = (
                "refused" if refused else "no_provider" if refused is None else "call"
            )
            embed_failures.labels(reason=reason).inc()
            raise

    return wrapper


def short_task_name(name: str | None) -> str:
    return (name or "unknown").replace("worker.tasks.", "")


def observe_finished(name: str | None, state: str | None, retval: Any) -> None:
    short = short_task_name(name)
    task_runs.labels(task=short, state=state or "UNKNOWN").inc()
    if short.endswith("process_document") and isinstance(retval, dict):
        documents_processed.labels(status=str(retval.get("status") or "unknown")).inc()
        chunks_ingested.inc(int(retval.get("vectors") or 0))


_STATE_QUERIES: tuple[tuple[str, str, str, str], ...] = (
    (
        "abenix_kb_documents",
        "Documents by status",
        "status",
        "SELECT status::text, count(*) FROM documents GROUP BY 1",
    ),
    (
        "abenix_kb_cognify_jobs",
        "Cognify jobs by status",
        "status",
        "SELECT status::text, count(*) FROM cognify_jobs GROUP BY 1",
    ),
    (
        "abenix_kb_reembed_jobs",
        "Re-embed jobs by status",
        "status",
        "SELECT status, count(*) FROM kb_reembed_jobs GROUP BY 1",
    ),
    (
        "abenix_kb_delete_jobs",
        "Collection deletes by status",
        "status",
        "SELECT status, count(*) FROM kb_delete_jobs GROUP BY 1",
    ),
    (
        "abenix_kb_connector_sources",
        "Connector sources by status",
        "status",
        "SELECT status, count(*) FROM kb_connector_sources GROUP BY 1",
    ),
)
_VALUE_QUERIES: tuple[tuple[str, str, str], ...] = (
    (
        "abenix_kb_cognify_documents_pending",
        "Ready documents in graph collections not yet in the graph",
        "SELECT count(*) FROM documents d JOIN knowledge_collections k ON k.id = d.kb_id "
        "WHERE k.graph_enabled AND d.cognified_at IS NULL AND d.status::text = 'READY'",
    ),
    (
        "abenix_kb_cognify_documents_processed",
        "Documents processed by Cognify jobs still running",
        "SELECT COALESCE(sum(documents_processed), 0) FROM cognify_jobs "
        "WHERE status::text NOT IN ('COMPLETE', 'FAILED', 'PENDING')",
    ),
    (
        "abenix_kb_reembed_chunks_done",
        "Chunks staged by re-embed jobs still live",
        "SELECT COALESCE(sum(chunks_done), 0) FROM kb_reembed_jobs "
        "WHERE finished_at IS NULL",
    ),
    (
        "abenix_kb_connector_items_failed",
        "Connector items whose last attempt failed",
        "SELECT count(*) FROM kb_connector_items WHERE status = 'failed'",
    ),
)


def _queues() -> list[str]:
    raw = os.environ.get("WORKER_METRICS_QUEUES", "documents,cognify")
    return [q.strip() for q in raw.split(",") if q.strip()]


class KnowledgeCollector:
    """Read at scrape time, so a stalled worker still reports the queue behind it."""

    def collect(self) -> Iterable[Any]:
        depth = GaugeMetricFamily(
            "abenix_kb_queue_depth", "Tasks waiting in a worker queue", labels=["queue"]
        )
        try:
            import redis

            r = redis.Redis.from_url(
                os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1"),
                socket_timeout=2,
                socket_connect_timeout=2,
            )
            for queue in _queues():
                depth.add_metric([queue], float(r.llen(queue)))
        except Exception as e:
            logger.debug("queue depth unavailable: %s", e)
        yield depth
        yield from self._database()

    def _database(self) -> Iterable[Any]:
        import psycopg2

        from worker.tasks.document_processor import _sync_db_url

        try:
            conn = psycopg2.connect(
                _sync_db_url(),
                connect_timeout=3,
                options="-c statement_timeout=5000",
            )
        except Exception as e:
            logger.debug("knowledge state metrics unavailable: %s", e)
            return
        out: list[Any] = []
        try:
            with conn.cursor() as cur:
                for name, doc, label, sql in _STATE_QUERIES:
                    family = GaugeMetricFamily(name, doc, labels=[label])
                    try:
                        cur.execute(sql)
                        for key, value in cur.fetchall():
                            family.add_metric([str(key)], float(value))
                    except Exception as e:
                        conn.rollback()
                        logger.debug("%s skipped: %s", name, e)
                    out.append(family)
                for name, doc, sql in _VALUE_QUERIES:
                    try:
                        cur.execute(sql)
                        out.append(
                            GaugeMetricFamily(name, doc, value=float(cur.fetchone()[0]))
                        )
                    except Exception as e:
                        conn.rollback()
                        logger.debug("%s skipped: %s", name, e)
        finally:
            conn.close()
        yield from out


def build_registry() -> CollectorRegistry:
    from prometheus_client import multiprocess

    registry = CollectorRegistry()
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        multiprocess.MultiProcessCollector(registry)
    registry.register(KnowledgeCollector())
    return registry


def prepare_files() -> None:
    folder = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not folder:
        return
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder, exist_ok=True)


def start_server() -> Any:
    from prometheus_client import start_http_server

    server, thread = start_http_server(int(PORT), registry=build_registry())
    logger.info("worker metrics on port %s", PORT)
    return server, thread


def install(celery_signals: Any) -> None:
    import time

    started: dict[str, float] = {}

    @celery_signals.task_prerun.connect(weak=False)
    def _pre(task_id: str = "", **_kw: Any) -> None:
        started[task_id] = time.monotonic()

    @celery_signals.task_postrun.connect(weak=False)
    def _post(
        task_id: str = "",
        task: Any = None,
        retval: Any = None,
        state: str | None = None,
        **_kw: Any,
    ) -> None:
        name = getattr(task, "name", None)
        began = started.pop(task_id, None)
        if began is not None:
            task_seconds.labels(task=short_task_name(name)).observe(
                time.monotonic() - began
            )
        observe_finished(name, state, retval)

    if not PORT:
        return

    @celery_signals.worker_init.connect(weak=False)
    def _serve(**_kw: Any) -> None:
        prepare_files()
        try:
            start_server()
        except OSError as e:
            logger.warning("worker metrics server did not start: %s", e)

    @celery_signals.worker_process_shutdown.connect(weak=False)
    def _child_gone(pid: int | None = None, **_kw: Any) -> None:
        from prometheus_client import multiprocess

        multiprocess.mark_process_dead(pid or os.getpid())
