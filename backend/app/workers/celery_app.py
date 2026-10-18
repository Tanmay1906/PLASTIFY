"""PLASTIFY Celery Application Initialization.

Configures asynchronous task execution with Redis broker and backend.
"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "plastify_worker",
    broker=settings.celery_broker_url_constructed,
    backend=settings.celery_result_backend_constructed,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,               # Acknowledge tasks only after successful execution
    task_reject_on_worker_lost=True,   # Re-queue task if worker process crashes mid-execution
    task_time_limit=300,        # 5 minutes maximum runtime
    task_soft_time_limit=270,   # soft warning at 4.5 minutes
    worker_prefetch_multiplier=1,
    worker_hijack_root_logger=False,  # Allow Plastify structured logging
)
