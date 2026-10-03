import os

from celery import Celery

broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1")
result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

celery_app = Celery(
    "abenix_worker",
    broker=broker_url,
    backend=result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=int(os.environ.get("CELERY_PREFETCH_MULTIPLIER", "1")),
    task_acks_late=os.environ.get("CELERY_TASK_ACKS_LATE", "true").lower() == "true",
    task_reject_on_worker_lost=os.environ.get(
        "CELERY_TASK_REJECT_ON_WORKER_LOST", "true"
    ).lower()
    == "true",
    task_acks_on_failure_or_timeout=False,
    broker_transport_options={
        "visibility_timeout": int(os.environ.get("CELERY_VISIBILITY_TIMEOUT", "21600")),
    },
    result_expires=int(os.environ.get("CELERY_RESULT_EXPIRES", "86400")),
    task_soft_time_limit=int(os.environ.get("CELERY_TASK_SOFT_TIME_LIMIT", "1500")),
    task_time_limit=int(os.environ.get("CELERY_TASK_TIME_LIMIT", "1800")),
    task_routes={
        "worker.tasks.document_processor.*": {"queue": "documents"},
        "worker.tasks.cognify_task.*": {"queue": "cognify"},
        "worker.tasks.kb_reembed.*": {"queue": "documents"},
        "worker.tasks.pinecone_vacuum.*": {"queue": "documents"},
    },
)

celery_app.conf.update(
    include=[
        "worker.tasks.document_processor",
        "worker.tasks.cognify_task",
        "worker.tasks.kb_reembed",
        "worker.tasks.pinecone_vacuum",
    ],
)
