"""Execution evidence survives process death; retries never re-execute a task."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time

from fastapi.testclient import TestClient

from variaq.campaigns.model import ExperimentCampaign
from variaq.services import VariaQService
from variaq.web.app import create_app
from variaq.web.tasks import CampaignTask, CampaignTaskManager


def _definition():
    return {
        "name": "web-test",
        "family": "maxcut",
        "problem_sizes": [4],
        "problem_seeds": [1],
        "solvers": ["exact", "heuristic"],
        "generator_parameters": {"edge_probability": 0.5},
    }


def _wait_for_task(client, task_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        task = client.get(f"/api/v1/campaigns/tasks/{task_id}").json()["task"]
        if task["status"] in {"completed", "failed", "interrupted"}:
            return task
        time.sleep(0.02)
    raise AssertionError("Task did not finish within 10 seconds")


def _service(root):
    (root / "problems").mkdir(exist_ok=True)
    (root / "reports").mkdir(exist_ok=True)
    return VariaQService(root / "runs.sqlite3", root / "problems", root / "reports")


def test_duplicate_submission_and_restart_preserve_original_task(tmp_path):
    service = _service(tmp_path)
    app = create_app(service)
    client = TestClient(app)
    payload = {"definition": _definition()}
    first = client.post("/api/v1/campaigns/run", json=payload).json()["task"]
    task = _wait_for_task(client, first["task_id"])
    assert task["status"] == "completed"
    assert service.store.count() == 2
    for _ in range(2):
        retry = client.post("/api/v1/campaigns/run", json=payload).json()["task"]
        assert retry["task_id"] == first["task_id"]
    app.state.tasks._thread.join(timeout=5)
    app.state.tasks._journal.close()
    restarted = TestClient(create_app(_service(tmp_path)))
    restored = restarted.get(f"/api/v1/campaigns/tasks/{first['task_id']}").json()["task"]
    assert restored["status"] == "completed"
    assert restored["completed_runs"] == 2
    assert restarted.post("/api/v1/campaigns/run", json=payload).json()["task"] == restored
    assert service.store.count() == 2
    with sqlite3.connect(service.db_path) as connection:
        assert connection.execute("SELECT version FROM schema_info").fetchone()[0] == 1


def test_second_manager_cannot_execute_or_interrupt_live_owner(tmp_path):
    service = _service(tmp_path)
    owner = CampaignTaskManager()
    owner.bind(service)
    owner._journal.save(CampaignTask("task-live", status="running").to_dict(), "live")
    observer = CampaignTaskManager()
    observer.bind(service)
    assert not observer._journal.can_execute
    assert observer.get("task-live").status == "running"
    assert (
        observer.start(
            service,
            {"campaign_format_version": "1", **_definition()},
            override_max_runs=False,
            max_runs=500,
            planned_runs=2,
        )
        is None
    )


def test_shutdown_keeps_worker_slot_for_accepted_task_before_thread_start(tmp_path):
    service = _service(tmp_path)
    owner = CampaignTaskManager()
    owner.bind(service)
    owner._current = CampaignTask("task-accepted", status="starting")
    owner.close()
    observer = CampaignTaskManager()
    observer.bind(service)
    assert not observer._journal.can_execute
    owner._current.status = "interrupted"
    owner.close()
    observer.close()


def test_process_death_between_solver_calls_retains_completed_attempt(tmp_path):
    # An actual child exits after its first recorded run while the matrix is incomplete.
    code = r"""
import os, sys, time
from pathlib import Path
from variaq.services import VariaQService
from variaq.web.app import create_app
root = Path(sys.argv[1])
(root / "problems").mkdir()
(root / "reports").mkdir()
service = VariaQService(root / "runs.sqlite3", root / "problems", root / "reports")
original = service.run_campaign
def run(definition, **kwargs):
    recorded = kwargs["on_run_recorded"]
    def die(run, completed):
        recorded(run, completed)
        os._exit(23)
    kwargs["on_run_recorded"] = die
    return original(definition, **kwargs)
service.run_campaign = run
app = create_app(service)
definition = {"campaign_format_version": "1", "name": "kill-test", "family": "maxcut",
              "problem_sizes": [4], "problem_seeds": [1], "solvers": ["exact", "heuristic"]}
app.state.tasks.start(service, definition, override_max_runs=False, max_runs=500, planned_runs=2)
time.sleep(15)
raise RuntimeError("worker failed to exit")
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        capture_output=True,
        timeout=20,
        env=os.environ.copy(),
    )
    assert result.returncode == 23, result.stderr.decode()
    service = _service(tmp_path)
    app = create_app(service)
    task = app.state.tasks.current()
    assert task.status == "interrupted"
    assert task.planned_runs == 2 and task.completed_runs == 1
    assert service.store.count() == 1
    assert len(service.campaign_store.get_run_ids(task.campaign_id)) == 1
    definition = service.campaign_store.get_campaign(task.campaign_id).to_dict()
    duplicate = app.state.tasks.start(
        service, definition, override_max_runs=False, max_runs=500, planned_runs=2
    )
    assert duplicate.task_id == task.task_id
    assert service.store.count() == 1
    assert "not retried" in task.error["message"]


def test_reconcile_committed_run_without_membership_or_task_update(tmp_path):
    from dataclasses import replace

    from variaq.experiments.runner import ExperimentRunner
    from variaq.models import SolverConfig
    from variaq.problems.maxcut import MaxCutProblem
    from variaq.solvers.base import get_solver

    service = _service(tmp_path)
    manager = CampaignTaskManager()
    manager.bind(service)
    definition = {"campaign_format_version": "1", **_definition()}
    cid = service.campaign_store.save_campaign(ExperimentCampaign.from_dict(definition))
    task = CampaignTask("task-orphan", status="running", planned_runs=2, campaign_id=cid)
    manager._journal.save(task.to_dict(), cid)
    runner = ExperimentRunner(service.store)
    run = runner._execute(
        MaxCutProblem.generate(4, 0.5, 1), get_solver("exact"), SolverConfig(), "benchmark-orphan"
    )
    run = replace(
        run, environment={**run.environment, "campaign_id": cid, "web_task_id": task.task_id}
    )
    service.store.save(run)
    manager._journal.close()
    restarted = CampaignTaskManager()
    restarted.bind(service)
    assert restarted.get(task.task_id).completed_runs == 1
    assert restarted.get(task.task_id).status == "interrupted"
    assert service.campaign_store.get_run_ids(cid) == [run.run_id]
    restarted._journal.reconcile()
    assert service.store.count() == 1
    assert service.campaign_store.get_run_ids(cid) == [run.run_id]


def test_historical_empty_campaign_is_not_silently_reexecuted(tmp_path):
    service = _service(tmp_path)
    definition = {"campaign_format_version": "1", **_definition()}
    service.campaign_store.save_campaign(ExperimentCampaign.from_dict(definition))
    client = TestClient(create_app(service))
    response = client.post("/api/v1/campaigns/run", json={"definition": _definition()})
    assert response.status_code == 400
    assert "historical execution state" in response.json()["error"]["message"]
    assert service.store.count() == 0
