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
    task_routes={
        "worker.tasks.agent_tasks.*": {"queue": "agents"},
        "worker.tasks.document_processor.*": {"queue": "documents"},
        "worker.tasks.export_tasks.*": {"queue": "exports"},
        "worker.tasks.cognify_task.*": {"queue": "cognify"},
    },
)

celery_app.conf.update(
    include=[
        "worker.tasks.agent_tasks",
        "worker.tasks.document_processor",
        "worker.tasks.cognify_task",
    ],
)
