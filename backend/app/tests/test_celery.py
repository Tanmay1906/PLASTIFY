"""Tests for Celery Worker Tasks and Configurations."""

from app.workers.celery_app import celery_app
from app.workers.tasks import celery_ping_task, system_maintenance_task


def test_celery_task_registration():
    """Verify that tasks are properly registered with the Celery app."""
    registered = celery_app.tasks
    assert "app.workers.tasks.celery_ping" in registered
    assert "app.workers.tasks.system_maintenance" in registered


def test_celery_ping_task_execution():
    """Execute celery_ping_task directly in synchronous test mode."""
    payload = {"source": "unit_test", "timestamp": "2026-10-10T00:00:00Z"}
    result = celery_ping_task.apply(args=[payload]).get()
    assert result["status"] == "SUCCESS"
    assert result["result"] == "pong"
    assert result["received_payload"] == payload


def test_system_maintenance_task_execution():
    """Execute system_maintenance_task directly in synchronous test mode."""
    result = system_maintenance_task.apply().get()
    assert result["status"] == "COMPLETED"
    assert "maintenance" in result["message"]
