from __future__ import annotations

from dataclasses import replace

import pytest

from variaq.errors import ValidationError
from variaq.experiments.runner import ExperimentRunner
from variaq.experiments.storage import ExperimentStore
from variaq.models import SolverConfig
from variaq.problems.maxcut import MaxCutProblem
from variaq.solvers.exact import ExactSolver


def test_stored_exact_reference_uses_authoritative_solution(tmp_path):
    store = ExperimentStore(tmp_path / "runs.sqlite3")
    runner = ExperimentRunner(store)
    problem = MaxCutProblem.from_edges(3, [(0, 1), (1, 2)])
    run = runner._execute(problem, ExactSolver(), SolverConfig(), None)
    store.save(replace(run, result=replace(run.result, objective=999.0)))
    assert store.exact_objective(problem.problem_id) == 2.0


def test_optional_gpu_memory_unavailable_does_not_fail_measurement(monkeypatch):
    from subprocess import CompletedProcess

    from variaq.solvers.cudaq_qaoa import _optional_gpu_metadata

    monkeypatch.setattr("variaq.solvers.cudaq_qaoa.shutil.which", lambda _: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(
        "variaq.solvers.cudaq_qaoa.subprocess.run",
        lambda *a, **k: CompletedProcess([], 0, "GPU, N/A, driver\n", ""),
    )
    metadata = _optional_gpu_metadata()
    assert metadata["gpu_count"] == 1
    assert metadata["gpus"][0]["total_memory_mib"] is None


def test_optional_gpu_probe_timeout_is_bounded_and_nonfatal(monkeypatch):
    from subprocess import TimeoutExpired

    from variaq.solvers.cudaq_qaoa import _optional_gpu_metadata

    monkeypatch.setattr("variaq.solvers.cudaq_qaoa.shutil.which", lambda _: "/usr/bin/nvidia-smi")

    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 3
        assert "shell" not in kwargs
        raise TimeoutExpired(args[0], 3)

    monkeypatch.setattr("variaq.solvers.cudaq_qaoa.subprocess.run", timeout)
    assert _optional_gpu_metadata() == {}


def test_gpu_runtime_failure_is_persisted_and_campaign_continues(tmp_path, monkeypatch):
    from variaq.campaigns.model import ExperimentCampaign
    from variaq.campaigns.runner import CampaignRunner
    from variaq.campaigns.store import CampaignStore
    from variaq.solvers.base import Solver

    class LostGpu(Solver):
        name = "cudaq-gpu"
        version = "test"
        supported_families = frozenset({"maxcut"})

        def solve(self, problem, config):
            raise RuntimeError("simulated GPU device loss")

    monkeypatch.setattr(
        "variaq.campaigns.runner.get_solver",
        lambda name: LostGpu() if name == "cudaq-gpu" else ExactSolver(),
    )
    store = ExperimentStore(tmp_path / "runs.sqlite3")
    memberships = CampaignStore(store.path)
    campaign = ExperimentCampaign(
        name="device-loss",
        family="maxcut",
        problem_sizes=(3,),
        problem_seeds=(1, 2),
        solvers=("cudaq-gpu", "exact"),
    )
    summary = CampaignRunner(ExperimentRunner(store), memberships, tmp_path / "problems").run(
        campaign
    )
    assert summary["completed_runs"] == 4
    assert summary["status_summary"]["failed"] == 2
    assert summary["status_summary"]["success"] == 2
    assert store.count() == len(memberships.get_run_ids(summary["campaign_id"])) == 4
    failed = [store.get(row["run_id"]) for row in store.list_runs() if row["status"] == "failed"]
    assert all("simulated GPU device loss" in run.result.errors[0] for run in failed)


def test_skipped_work_is_distinct_from_recorded_attempts(tmp_path):
    from variaq.campaigns.model import ExperimentCampaign
    from variaq.campaigns.runner import CampaignRunner
    from variaq.campaigns.store import CampaignStore

    store = ExperimentStore(tmp_path / "runs.sqlite3")
    campaign = ExperimentCampaign(
        name="unsupported-family",
        family="graph-partition",
        problem_sizes=(2,),
        problem_seeds=(1,),
        solvers=("exact", "cudaq-gpu"),
        repeats=2,
    )
    summary = CampaignRunner(
        ExperimentRunner(store), CampaignStore(store.path), tmp_path / "problems"
    ).run(campaign)
    assert summary["requested_runs"] == 4
    assert summary["completed_runs"] == 2 and summary["skipped_runs"] == 2
    assert summary["status_summary"]["skipped"] == 2
    assert store.count() == 2


def test_inconsistent_exact_solutions_do_not_establish_optimum(tmp_path):
    store = ExperimentStore(tmp_path / "runs.sqlite3")
    runner = ExperimentRunner(store)
    problem = MaxCutProblem.from_edges(2, [(0, 1)])
    run = runner.run_one(problem, ExactSolver(), SolverConfig())
    store.save(
        replace(
            run, run_id="run-disagree", result=replace(run.result, solution=(0, 0), objective=0.0)
        )
    )
    assert store.exact_objective(problem.problem_id) is None


def test_report_overwrite_rejects_symlink_and_unsafe_id(tmp_path):
    from variaq.analysis.models import AnalysisQuery
    from variaq.analysis.operations import analyze_runs
    from variaq.analysis.reports import export_report, generate_report

    report = generate_report(analyze_runs([], AnalysisQuery()))
    outside = tmp_path / "outside.txt"
    outside.write_text("preserve")
    reports = tmp_path / "reports"
    reports.mkdir()
    try:
        (reports / f"{report.report_id}.json").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    with pytest.raises(ValidationError, match="symlink"):
        export_report(report, reports, overwrite=True)
    assert outside.read_text() == "preserve"
    report.report_id = "../escape"
    with pytest.raises(ValidationError):
        export_report(report, reports, overwrite=True)


@pytest.mark.parametrize("field", ["solvers", "problem_sizes", "problem_seeds"])
def test_duplicate_campaign_slots_rejected(field):
    from variaq.campaigns.model import ExperimentCampaign

    definition = {
        "campaign_format_version": "1",
        "name": "duplicate",
        "family": "maxcut",
        "problem_sizes": [4],
        "problem_seeds": [1],
        "solvers": ["exact"],
    }
    definition[field] *= 2
    with pytest.raises(ValidationError, match="duplicates"):
        ExperimentCampaign.from_dict(definition)
