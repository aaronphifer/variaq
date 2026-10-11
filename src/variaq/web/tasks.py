"""In-process campaign execution task tracking for the local web UI.

Campaign execution is local and sequential — one campaign at a time,
owned by a daemon thread inside the server process. Task snapshots are retained
in SQLite, while experiment records remain append-only. After a restart, unfinished tasks
are marked interrupted without retrying execution. An OS-held file lock prevents
multiple web workers from executing against the same database.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from variaq.models import utc_now
from variaq.web.task_journal import TaskJournal

log = logging.getLogger("variaq.web.tasks")


@dataclass
class CampaignTask:
    task_id: str
    status: str = "starting"  # starting | running | completed | failed | interrupted
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
    kind: str = "campaign"
    source_run_id: str | None = None

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
            "kind": self.kind,
            "source_run_id": self.source_run_id,
        }


class CampaignTaskManager:
    """Owns the single background campaign worker, if one is active."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: CampaignTask | None = None
        self._thread: threading.Thread | None = None
        self._journal: TaskJournal | None = None

    def bind(self, service: Any) -> None:
        if self._journal is None:
            self._journal = TaskJournal(service.campaign_store)

    def close(self) -> None:
        """Release the worker slot only when no native call can still be running."""
        with self._lock:
            if (self._current is not None and self._current.status in {"starting", "running"}) or (
                self._thread is not None and self._thread.is_alive()
            ):
                log.warning("Worker still running; retaining execution lock until process exit")
                return
            if self._journal is not None:
                self._journal.close()

    def _save(self, task: CampaignTask, key: str | None = None) -> None:
        if self._journal is not None:
            self._journal.save(task.to_dict(), key)

    @staticmethod
    def _restore(data: dict | None) -> CampaignTask | None:
        return CampaignTask(**data) if data else None

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
        from variaq.campaigns.model import ExperimentCampaign, campaign_definition_id
        from variaq.errors import ValidationError

        campaign = ExperimentCampaign.from_dict(definition)
        campaign_id = campaign_definition_id(campaign)

        with self._lock:
            if self._journal is not None:
                existing = self._journal.get(request_key=campaign_id)
                if existing:
                    return self._restore(existing)
                if not self._journal.can_execute:
                    return None
                try:
                    service.campaign_store.get_campaign(campaign_id)
                except ValidationError:
                    pass
                else:
                    raise ValidationError(
                        "This campaign already exists with historical execution state. Inspect it "
                        "before planning a new campaign with a different name; "
                        "it cannot be resumed."
                    )
            if self._current is not None and self._current.status in {"starting", "running"}:
                return None
            task = CampaignTask(
                task_id=f"task-{uuid.uuid4().hex[:12]}",
                definition=definition,
                override_max_runs=override_max_runs,
                max_runs=max_runs,
                planned_runs=planned_runs,
                campaign_id=campaign_id,
            )
            self._save(task, campaign_id)
            self._current = task

        def work() -> None:
            with self._lock:
                task.status = "running"
                self._save(task)

            def on_run_recorded(_run: Any, completed: int) -> None:
                with self._lock:
                    task.completed_runs = completed
                    self._save(task)

            try:
                planned = ExperimentCampaign.from_dict(definition).requested_runs
                with self._lock:
                    task.planned_runs = planned
                summary = service.run_campaign(
                    definition,
                    override_max_runs=override_max_runs,
                    max_runs=max_runs,
                    on_run_recorded=on_run_recorded,
                    web_task_id=task.task_id,
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
                    self._save(task)

        self._thread = threading.Thread(target=work, name="variaq-campaign", daemon=True)
        self._thread.start()
        return task

    def current(self) -> CampaignTask | None:
        with self._lock:
            if self._journal is not None:
                return self._restore(self._journal.current())
            return self._current

    def start_reproduction(self, service: Any, run_id: str) -> CampaignTask | None:
        """Reproduction shares the one local execution slot with campaigns."""
        original = service.get_run(run_id)
        if not original["reproduction_eligible"]:
            from variaq.errors import ValidationError

            raise ValidationError("Only local experiments can be reproduced")
        with self._lock:
            key = "reproduction:" + run_id
            if self._journal is not None:
                existing = self._journal.get(request_key=key)
                if existing:
                    return self._restore(existing)
                if not self._journal.can_execute:
                    return None
            if self._current and self._current.status in {"starting", "running"}:
                return None
            task = CampaignTask(
                task_id=f"task-{uuid.uuid4().hex[:12]}",
                planned_runs=1,
                kind="reproduction",
                source_run_id=run_id,
            )
            self._save(task, key)
            self._current = task

        def work() -> None:
            with self._lock:
                task.status = "running"
                self._save(task)
            try:
                result = service.reproduce(run_id, web_task_id=task.task_id)
                with self._lock:
                    task.result = result
                    task.completed_runs = 1
                    task.status = "completed"
            except Exception as exc:
                log.exception("Reproduction task %s failed", task.task_id)
                with self._lock:
                    task.status = "failed"
                    task.error = {"type": type(exc).__name__, "message": str(exc)}
            finally:
                with self._lock:
                    task.finished_at = utc_now()
                    self._save(task)

        self._thread = threading.Thread(target=work, name="variaq-reproduce", daemon=True)
        self._thread.start()
        return task

    def get(self, task_id: str) -> CampaignTask | None:
        with self._lock:
            if self._journal is not None:
                return self._restore(self._journal.get(task_id=task_id))
            if self._current is not None and self._current.task_id == task_id:
                return self._current
        return None
