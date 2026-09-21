"""Campaign planning/execution, analysis, and report-flow tests through the API."""

from __future__ import annotations

import time


def _definition(sizes=(4,), seeds=(1,), solvers=("exact", "heuristic"), repeats=1):
    return {
        "name": "web-test",
        "family": "maxcut",
        "problem_sizes": list(sizes),
        "problem_seeds": list(seeds),
        "solvers": list(solvers),
        "repeats": repeats,
        "base_seed": 0,
        "generator_parameters": {"edge_probability": 0.5},
    }


def _wait_for_task(client, task_id, attempts=240):
    task: dict | None = None
    for _ in range(attempts):
        task = client.get(f"/api/v1/campaigns/tasks/{task_id}").json()["task"]
        if task is not None and task["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)
    assert task is not None, "task never returned a terminal status"
    return task


def test_campaign_plan(web_env):
    plan = (
        web_env["client"]
        .post(
            "/api/v1/campaigns/plan", json={"definition": _definition(sizes=(4, 5), seeds=(1, 2))}
        )
        .json()
    )
    assert plan["problem_instance_count"] == 4
    assert plan["requested_runs"] == 8
    assert plan["exceeds_default_max"] is False
    assert len(plan["solver_breakdown"]) == 2


def test_campaign_plan_over_limit_warns(web_env):
    plan = web_env["client"].post(
        "/api/v1/campaigns/plan",
        json={
            "definition": _definition(
                sizes=list(range(1, 10)),
                seeds=list(range(1, 8)),
                solvers=("exact", "heuristic"),
                repeats=5,
            )
        },
    )
    assert plan.status_code == 200
    body = plan.json()
    assert 9 * 7 * 2 * 5 > 500
    assert body["exceeds_default_max"] is True
    assert any("maximum" in w for w in body["warnings"])


def test_campaign_run_guard_blocks_without_override(web_env):
    # Exceeds VariaQ's DEFAULT_MAX_RUNS while staying inside the API schema's
    # field bounds, so the VariaQ guard (not the schema) is what fires.
    definition = _definition(
        sizes=list(range(1, 18)),
        seeds=list(range(1, 16)),
        solvers=("exact", "heuristic"),
        repeats=1,
    )
    assert 17 * 15 * 2 > 500
    response = web_env["client"].post("/api/v1/campaigns/run", json={"definition": definition})
    assert response.status_code == 200
    task = _wait_for_task(web_env["client"], response.json()["task"]["task_id"])
    assert task["status"] == "failed"
    assert "maximum" in task["error"]["message"]


def test_campaign_run_small_succeeds(web_env):
    response = web_env["client"].post(
        "/api/v1/campaigns/run", json={"definition": _definition(sizes=(4,), seeds=(1,))}
    )
    task = _wait_for_task(web_env["client"], response.json()["task"]["task_id"])
    assert task["status"] == "completed"
    campaign_id = task["campaign_id"]
    detail = web_env["client"].get(f"/api/v1/campaigns/{campaign_id}").json()
    assert detail["completed_runs"] == 2


def test_campaign_run_conflict_returns_409(web_env):
    """A second campaign cannot start while one runs."""
    import threading

    from fastapi.testclient import TestClient

    from variaq.web.app import create_app
    from variaq.web.tasks import CampaignTask, CampaignTaskManager

    manager = CampaignTaskManager()
    with manager._lock:
        manager._current = CampaignTask(task_id="task-busy", status="running")
        manager._thread = threading.Thread(target=lambda: None)
    app = create_app(web_env["service"], task_manager=manager)
    client = TestClient(app)
    response = client.post("/api/v1/campaigns/run", json={"definition": _definition()})
    assert response.status_code == 409


def _run_small_campaign(client):
    response = client.post("/api/v1/campaigns/run", json={"definition": _definition()})
    task = _wait_for_task(client, response.json()["task"]["task_id"])
    assert task["status"] == "completed"
    return task["campaign_id"]


def test_analysis_campaign(web_env):
    campaign_id = _run_small_campaign(web_env["client"])
    analysis = (
        web_env["client"]
        .post(
            f"/api/v1/analysis/campaigns/{campaign_id}",
            json={"group_by": ["problem_id", "solver"]},
        )
        .json()
    )
    assert len(analysis["source_run_ids"]) == 2
    assert analysis["groups"]
    first = analysis["groups"][0]
    assert "quality" in first and "feasibility" in first and "timing" in first
    # Query intent is echoed back for provenance.
    assert analysis["query"]["campaign_id"] == campaign_id


def test_analysis_requires_selection(web_env):
    response = web_env["client"].post("/api/v1/analysis/runs", json={})
    assert response.status_code == 400


def test_report_generate_and_download(web_env):
    campaign_id = _run_small_campaign(web_env["client"])
    created = (
        web_env["client"]
        .post(
            f"/api/v1/reports/campaigns/{campaign_id}",
            json={"formats": ["json", "markdown"]},
        )
        .json()
    )
    report_id = created["report_id"]

    listing = web_env["client"].get("/api/v1/reports").json()
    assert listing["total"] == 1
    entry = listing["reports"][0]
    assert entry["report_id"] == report_id
    assert entry["source_run_count"] == 2
    assert set(entry["formats"]) == {"json", "markdown"}

    download = web_env["client"].get(f"/api/v1/reports/{report_id}/files/{report_id}.json")
    assert download.status_code == 200


def test_report_without_runs_fails(web_env):
    response = web_env["client"].post(
        "/api/v1/reports/campaigns/campaign-nothing", json={"formats": ["json"]}
    )
    assert response.status_code in (400, 404)
