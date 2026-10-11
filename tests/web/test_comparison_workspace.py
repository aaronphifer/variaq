"""The UI's bounded evidence selection uses existing scientific semantics."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest

from variaq.campaigns.model import ExperimentCampaign
from variaq.models import SolveStatus


def selected(client, **kwargs):
    return client.post(
        "/api/v1/comparison",
        json={
            "run_ids": ["run-test-exact", "run-test-heuristic"],
            **kwargs,
        },
    )


def test_standalone_runs_are_unpaired_with_authoritative_reference(web_env):
    response = selected(web_env["client"])
    assert response.status_code == 200
    data = response.json()
    assert data["selected_count"] == data["window_count"] == 2
    instance = data["analysis"]["instances"][0]
    assert instance["reference_optimum"] is not None
    assert instance["reference_run_ids"] == ["run-test-exact"]
    assert not data["analysis"]["comparisons"][0]["pairs"]
    assert all(r["objective"] is not None for r in instance["runs"])
    assert data["repeat_scaling"]


def test_pairing_preserved_and_repeats_not_mixed(web_env):
    service = web_env["service"]
    ids = []
    for name in ("exact", "heuristic"):
        source = service.store.get("run-test-" + name)
        run = replace(
            source,
            run_id="paired-" + name,
            benchmark_id="bench-shared",
            environment={"benchmark_protocol": {"repeat_index": 0}},
        )
        service.store.save(run)
        ids.append(run.run_id)
    data = selected(web_env["client"], run_ids=ids).json()
    pair = data["analysis"]["comparisons"][0]["pairs"][0]
    assert pair["left_run_id"] == "paired-exact"
    assert pair["right_run_id"] == "paired-heuristic"
    assert pair["repeat_key"] == "repeat:0"
    assert pair["numerical_correctness"]["max_expectation_delta"] is None


@pytest.mark.parametrize("status", [SolveStatus.FAILED, SolveStatus.UNAVAILABLE])
def test_failed_attempts_not_zero_measurements(web_env, status):
    service = web_env["service"]
    source = service.store.get("run-test-heuristic")
    run = replace(
        source,
        run_id="attempt-" + status.value,
        result=replace(
            source.result,
            status=status,
            solution=None,
            objective=None,
            feasible=False,
            wall_time_seconds=12,
        ),
    )
    service.store.save(run)
    data = selected(web_env["client"], run_ids=[run.run_id]).json()
    measurement = data["analysis"]["instances"][0]["runs"][0]
    assert measurement["objective"] is None
    assert measurement["feasible"] is None
    assert measurement["timing"]["wall_time_seconds"] is None
    assert measurement["attempt_wall_time_seconds"] == 12
    assert measurement["missing_measurements"]["wall_time_seconds"]
    assert data["repeat_scaling"][0]["wall"]["count"] == 0


def test_filter_removes_reference_and_null_gap_has_reason(web_env):
    data = selected(web_env["client"], solver="heuristic").json()
    instance = data["analysis"]["instances"][0]
    assert instance["reference_optimum"] is None
    assert instance["reference_reason"]
    assert instance["runs"][0]["optimality_gap_percent"] is None
    assert instance["runs"][0]["missing_measurements"]["optimality_gap_percent"]


def test_historical_absent_metadata_is_unknown(web_env):
    source = web_env["service"].store.get("run-test-heuristic")
    old = replace(
        source,
        run_id="historical",
        environment={},
        result=replace(
            source.result,
            solver_time_seconds=None,
            backend=replace(source.result.backend, metrics={}),
        ),
    )
    web_env["service"].store.save(old)
    measurement = selected(web_env["client"], run_ids=["historical"]).json()["analysis"][
        "instances"
    ][0]["runs"][0]
    assert measurement["timing"]["solver_time_seconds"] is None
    assert measurement["timing_scopes"]["wall"] is None
    assert measurement["cold_start_verified"] is None
    assert not selected(web_env["client"], run_ids=["historical"]).json()["analysis"][
        "comparisons"
    ][0]["pairs"]


def test_empty_campaign_and_filtered_evidence(web_env):
    service = web_env["service"]
    campaign = ExperimentCampaign(
        name="empty", family="maxcut", problem_sizes=(4,), problem_seeds=(1,), solvers=("exact",)
    )
    cid = service.campaign_store.save_campaign(campaign)
    response = web_env["client"].post("/api/v1/comparison", json={"campaign_id": cid})
    assert response.status_code == 200
    assert response.json()["analysis"]["instances"] == []
    assert response.json()["selected_count"] == 0
    assert selected(web_env["client"], size=999).json()["analysis"]["instances"] == []
    assert selected(web_env["client"], warmup="explicit_warmup").json()["selected_count"] == 0


def test_bounded_windows_not_silent_truncation(web_env):
    first = selected(web_env["client"], limit=1).json()
    second = selected(web_env["client"], limit=1, offset=1).json()
    assert first["total"] == second["total"] == 2
    assert first["window_count"] == second["window_count"] == 1
    assert set(first["analysis"]["source_run_ids"]).isdisjoint(second["analysis"]["source_run_ids"])
    assert first["selection"]["limit"] == 1


@pytest.mark.parametrize(
    "payload,status",
    [
        ({}, 400),
        ({"run_ids": []}, 422),
        ({"run_ids": ["missing"]}, 404),
        ({"run_ids": ["run-test-exact"] * 501}, 422),
        ({"run_ids": ["run-test-exact"] * 2}, 400),
        ({"campaign_id": "missing"}, 404),
        ({"run_ids": ["run-test-exact"], "campaign_id": "anything"}, 400),
        ({"run_ids": ["run-test-exact"], "limit": 501}, 422),
        ({"run_ids": ["run-test-exact"], "offset": -1}, 422),
        ({"run_ids": ["run-test-exact"], "warmup": "bogus"}, 422),
        ({"run_ids": ["run-test-exact"], "sql": "select 1"}, 422),
    ],
)
def test_selection_validation(web_env, payload, status):
    assert web_env["client"].post("/api/v1/comparison", json=payload).status_code == status


def test_selected_report_preserves_source_and_download_confinement(web_env):
    client = web_env["client"]
    result = client.post("/api/v1/comparison/reports", json={"run_ids": ["run-test-heuristic"]})
    assert result.status_code == 200
    rid = result.json()["report_id"]
    report = client.get(f"/api/v1/reports/{rid}").json()["report"]
    assert report["source_run_ids"] == ["run-test-heuristic"]
    assert report["analysis"]["instances"][0]["reference_optimum"] is None
    for suffix in (".json", ".md", "_runs.csv", "_pairs.csv", "_repeats.csv"):
        assert client.get(f"/api/v1/reports/{rid}/files/{rid}{suffix}").status_code == 200
    assert client.get(f"/api/v1/reports/{rid}/files/arbitrary.txt").status_code == 403


def test_solver_configuration_round_trips_through_plan(web_env):
    response = web_env["client"].post(
        "/api/v1/campaigns/plan",
        json={
            "definition": {
                "name": "controls",
                "family": "maxcut",
                "problem_sizes": [4],
                "problem_seeds": [11],
                "solvers": ["exact"],
                "solver_config": {"exact": {"parameters": {"max_states": 256}}},
            }
        },
    )
    assert response.status_code == 200
    assert (
        response.json()["definition"]["solver_config"]["exact"]["parameters"]["max_states"] == 256
    )


def test_reproduction_creates_new_record_with_lineage(web_env):
    client = web_env["client"]
    response = client.post("/api/v1/runs/run-test-exact/reproduce", json={})
    assert response.status_code == 200
    task_id = response.json()["task"]["task_id"]
    for _ in range(100):
        task = client.get("/api/v1/campaigns/tasks/" + task_id).json()["task"]
        if task["status"] in {"completed", "failed"}:
            break
        time.sleep(0.01)
    assert task["status"] == "completed"
    run = task["result"]
    assert run["rerun_of"] == "run-test-exact"
    assert run["run_id"] != "run-test-exact"
    assert client.get("/api/v1/runs/" + run["run_id"]).status_code == 200


def test_reproduction_shares_execution_slot(web_env):
    from variaq.web.tasks import CampaignTask

    manager = web_env["client"].app.state.tasks
    manager._current = CampaignTask(task_id="busy", status="running")
    assert (
        web_env["client"].post("/api/v1/runs/run-test-exact/reproduce", json={}).status_code == 409
    )
    assert web_env["client"].post("/api/v1/runs/missing/reproduce", json={}).status_code == 404


def test_pagination_not_limited_to_first_thousand_campaigns(web_env):
    service = web_env["service"]
    for i in range(3):
        service.campaign_store.save_campaign(
            ExperimentCampaign(
                name=str(i),
                family="maxcut",
                problem_sizes=(4,),
                problem_seeds=(i,),
                solvers=("exact",),
            )
        )
    page = web_env["client"].get("/api/v1/campaigns?limit=1&offset=2").json()
    assert page["total"] == 3
    assert len(page["campaigns"]) == 1
    assert page["campaigns"][0]["name"] == "0"


def test_campaign_rerun_with_fresh_creation_time_appends_execution(web_env):
    service = web_env["service"]
    definition = {
        "campaign_format_version": "1",
        "name": "rerun-browser",
        "family": "maxcut",
        "problem_sizes": [4],
        "problem_seeds": [11],
        "solvers": ["exact", "heuristic"],
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    first = service.run_campaign(definition)
    second = service.run_campaign({**definition, "created_at": "2026-02-01T00:00:00+00:00"})
    assert first["campaign_id"] == second["campaign_id"]
    assert set(first["run_ids"]).isdisjoint(second["run_ids"])
    cid = first["campaign_id"]
    assert service.campaign_store.get_campaign(cid).created_at == definition["created_at"]
    window = web_env["client"].get(f"/api/v1/campaigns/{cid}?limit=1&offset=1").json()
    assert len(window["runs"]) == 1
    assert window["completed_runs"] == 4
    assert web_env["client"].get(f"/api/v1/campaigns/{cid}?limit=0").status_code == 400
    data = web_env["client"].post("/api/v1/comparison", json={"campaign_id": cid}).json()
    pairs = data["analysis"]["comparisons"][0]["pairs"]
    assert len(pairs) == 2
    assert len({pair["benchmark_id"] for pair in pairs}) == 2


def test_comparison_export_reuses_timestamp(web_env):
    client = web_env["client"]
    payload = {"run_ids": ["run-test-exact", "run-test-heuristic"]}
    created = client.post("/api/v1/comparison/reports", json=payload)
    assert created.status_code == 200
    rid = created.json()["report_id"]
    first = client.get(f"/api/v1/reports/{rid}").json()["report"]["generated_at"]
    paths = [web_env["reports_dir"] / f"{rid}{suffix}" for suffix in (".json", ".md")]
    contents = [path.read_bytes() for path in paths]
    assert first in paths[1].read_text(encoding="utf-8")
    repeated = client.post("/api/v1/comparison/reports", json=payload)
    assert repeated.status_code == 200
    assert repeated.json()["report_id"] == rid
    assert client.get(f"/api/v1/reports/{rid}").json()["report"]["generated_at"] == first
    assert [path.read_bytes() for path in paths] == contents


def _create_symlink_or_skip(target: Path, outside: Path) -> None:
    try:
        target.symlink_to(outside)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip(f"Symlink creation privilege unavailable (WinError 1314): {exc}")
        raise


def test_comparison_export_refuses_write_symlinks(web_env):
    client = web_env["client"]
    payload = {"run_ids": ["run-test-exact", "run-test-heuristic"]}
    created = client.post("/api/v1/comparison/reports", json=payload)
    assert created.status_code == 200
    rid = created.json()["report_id"]
    target = web_env["reports_dir"] / f"{rid}.md"
    target.unlink()
    outside = web_env["reports_dir"].parent / "outside.md"
    outside.write_text("must remain unchanged", encoding="utf-8")
    _create_symlink_or_skip(target, outside)
    assert client.post("/api/v1/comparison/reports", json=payload).status_code == 403
    assert outside.read_text(encoding="utf-8") == "must remain unchanged"


def test_symlink_creation_skips_windows_privilege_denial(monkeypatch, tmp_path):
    error = OSError("A required privilege is not held by the client")
    error.winerror = 1314

    def denied(*args, **kwargs):
        raise error

    monkeypatch.setattr(Path, "symlink_to", denied)
    with pytest.raises(pytest.skip.Exception, match="WinError 1314"):
        _create_symlink_or_skip(tmp_path / "target", tmp_path / "outside")


@pytest.mark.parametrize("errno,winerror", [(13, None), (1, None), (28, None), (13, 5)])
def test_symlink_creation_preserves_unrelated_errors(monkeypatch, tmp_path, errno, winerror):
    error = OSError(errno, "Unrelated filesystem failure")
    if winerror is not None:
        error.winerror = winerror

    def failed(*args, **kwargs):
        raise error

    monkeypatch.setattr(Path, "symlink_to", failed)
    with pytest.raises(OSError) as raised:
        _create_symlink_or_skip(tmp_path / "target", tmp_path / "outside")
    assert raised.value is error


def test_reproduction_requires_json_intent_and_no_arbitrary_configuration(web_env):
    client = web_env["client"]
    path = "/api/v1/runs/run-test-exact/reproduce"
    assert client.post(path).status_code == 422
    assert client.post(path, data={"shell": "echo bad"}).status_code == 422
    assert client.post(path, json={"backend": "remote"}).status_code == 422
