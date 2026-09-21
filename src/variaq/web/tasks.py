"""In-process campaign execution task tracking for the local web UI.

0.7 campaign execution is local and sequential — one campaign at a time,
owned by a daemon thread inside the server process. This deliberately avoids
Redis/Celery/queue infrastructure. The task record is in-memory only: if the
server restarts mid-campaign, recorded runs remain in storage (append-only),
but the task status is lost and reported as unknown.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from variaq.models import utc_now

log = logging.getLogger("variaq.web.tasks")


@dataclass
class CampaignTask:
    task_id: str
    status: str = "starting"  # starting | running | completed | failed
    definition: dict[str, Any] = field(default_factory=dict)
    override_max_runs: bool = False
    max_runs: int = 500
    planned_runs: int | None = None
    completed_runs: int = 0
    created_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    campaign_id: str | None = None
    error: dict[str, str] | None = None
    result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "planned_runs": self.planned_runs,
            "completed_runs": self.completed_runs,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "campaign_id": self.campaign_id,
            "error": self.error,
            "result": self.result,
        }


class CampaignTaskManager:
    """Owns the single background campaign worker, if one is active."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: CampaignTask | None = None
        self._thread: threading.Thread | None = None

    def start(
        self,
        service: Any,
        definition: dict[str, Any],
        *,
        override_max_runs: bool,
        max_runs: int,
        planned_runs: int | None,
    ) -> CampaignTask | None:
        """Begin a campaign task, or return None if one is already active."""
        from variaq.campaigns.model import ExperimentCampaign

        with self._lock:
            if self._current is not None and self._current.status in {"starting", "running"}:
                return None
            task = CampaignTask(
                task_id=f"task-{uuid.uuid4().hex[:12]}",
                definition=definition,
                override_max_runs=override_max_runs,
                max_runs=max_runs,
                planned_runs=planned_runs,
            )
            self._current = task

        def work() -> None:
            with self._lock:
                task.status = "running"

            def on_run_recorded(_run: Any, completed: int) -> None:
                with self._lock:
                    task.completed_runs = completed

            try:
                planned = ExperimentCampaign.from_dict(definition).requested_runs
                with self._lock:
                    task.planned_runs = planned
                summary = service.run_campaign(
                    definition,
                    override_max_runs=override_max_runs,
                    max_runs=max_runs,
                    on_run_recorded=on_run_recorded,
                )
                with self._lock:
                    task.status = "completed"
                    task.result = summary
                    task.campaign_id = summary.get("campaign_id")
                    task.completed_runs = summary.get("completed_runs", task.completed_runs)
            except Exception as exc:  # noqa: BLE001 - surface structured failure
                log.exception("Campaign task %s failed", task.task_id)
                with self._lock:
                    task.status = "failed"
                    task.error = {"type": type(exc).__name__, "message": str(exc)}
            finally:
                with self._lock:
                    task.finished_at = utc_now()

        self._thread = threading.Thread(target=work, name="variaq-campaign", daemon=True)
        self._thread.start()
        return task

    def current(self) -> CampaignTask | None:
        with self._lock:
            return self._current

    def get(self, task_id: str) -> CampaignTask | None:
        with self._lock:
            if self._current is not None and self._current.task_id == task_id:
                return self._current
        return None
