"""Scientific pairing and reporting tests use only the dependency-free core."""

from __future__ import annotations

import csv
import io
import json
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

import pytest

from variaq.analysis.metrics import best_known_objective
from variaq.analysis.models import AnalysisQuery
from variaq.analysis.operations import analyze_runs
from variaq.analysis.reports import export_report, generate_report
from variaq.campaigns.model import ExperimentCampaign, campaign_definition_id
from variaq.campaigns.runner import CampaignRunner
from variaq.campaigns.store import CampaignStore
from variaq.cli import main
from variaq.errors import BackendUnavailableError, MissingOptionalDependency
from variaq.experiments.runner import ExperimentRunner
from variaq.experiments.storage import ExperimentStore
from variaq.models import ExperimentRun, OptimizationSense, SolverConfig, SolveStatus
from variaq.outputs import quantum_comparison_json_data
from variaq.problems.maxcut import MaxCutProblem
from variaq.problems.subset_selection import SubsetSelectionProblem
from variaq.solvers.cudaq_qaoa import _selected_target
from variaq.solvers.exact import ExactSolver


@pytest.fixture
def baseline(tmp_path):
    problem = MaxCutProblem.from_edges(3, [(0, 1, 1.0), (1, 2, 2.0)])
    runner = ExperimentRunner(ExperimentStore(tmp_path / "runs.db"))
    run = runner.benchmark(problem, [ExactSolver()], {"exact": SolverConfig(seed=42)})[0]
    return run


def variant(run, *, name="heuristic", solution=(0, 0, 1), seed=42, repeat=0, **fields):
    metrics = dict(run.result.backend.metrics)
    metrics.pop("solver_time_scope", None)
    result = replace(run.result, solver_name=name, solution=solution, **fields)
    result = replace(result, backend=replace(result.backend, metrics=metrics))
    return replace(
        run,
        run_id=f"{name}-{repeat}-{seed}",
        result=result,
        solver_config=SolverConfig(seed=seed),
        environment={"benchmark_protocol": {"repeat_index": repeat}},
    )


def analysis(runs):
    return analyze_runs(
        runs,
        AnalysisQuery(
            group_by=("problem_id", "solver"), include_failed=True, include_unavailable=True
        ),
        comparisons=("paired_solvers",),
    )


def test_authoritative_quality_and_per_problem_reference(baseline):
    candidate = variant(baseline, objective=999.0)
    result = analysis([candidate, baseline])
    m = next(r for r in result.instances[0]["runs"] if r["solver"] == "heuristic")
    assert m["objective"] == 2.0
    assert m["objective_matches_reported"] is False
    assert m["reference_optimum"] == 3.0
    assert m["optimality_gap_percent"] == pytest.approx(100 / 3)
    q = next(g.quality for g in result.groups if g.group_key["solver"] == "heuristic")
    assert q.mean_gap_percent == pytest.approx(100 / 3)
    assert q.success_at_optimum_rate == 0.0
    assert result.comparisons[0].pairs[0]["objective_improvement_left"] == 1.0


def test_pairing_repeat_and_execution_provenance(baseline):
    h0 = variant(baseline)
    h1 = variant(baseline, repeat=1, seed=43)
    e1 = replace(
        baseline, run_id="exact-1", environment={"benchmark_protocol": {"repeat_index": 1}}
    )
    unrelated = replace(h0, benchmark_id="different", run_id="unrelated")
    result = analysis([h1, e1, unrelated, h0, baseline])
    pairs = result.comparisons[0].pairs
    assert len(pairs) == 2
    assert {p["repeat_key"] for p in pairs} == {"repeat:0", "repeat:1"}
    assert all("unrelated" not in (p["left_run_id"], p["right_run_id"]) for p in pairs)
    assert analysis(list(reversed([h1, e1, unrelated, h0, baseline]))).to_dict() == result.to_dict()


def test_missing_and_duplicate_slots_are_not_zipped(baseline):
    h0 = variant(baseline)
    h1 = variant(baseline, repeat=1, seed=43)
    duplicate = replace(h0, run_id="duplicate")
    pairs = analysis([baseline, h0, duplicate, h1]).comparisons[0].pairs
    assert len(pairs) == 2
    assert pairs[0]["right_run_id"] is None
    assert "Ambiguous" in pairs[0]["missing_pairs"]["heuristic"]
    assert pairs[1]["left_run_id"] is None
    assert "No recorded run" in pairs[1]["missing_pairs"]["exact"]


@pytest.mark.parametrize("status", [SolveStatus.UNAVAILABLE, SolveStatus.FAILED])
def test_unsuccessful_runs_have_null_performance(baseline, status):
    candidate = variant(
        baseline,
        name="cudaq-gpu",
        status=status,
        solution=None,
        objective=None,
        feasible=False,
        wall_time_seconds=12.0,
    )
    result = analysis([baseline, candidate])
    m = next(r for r in result.instances[0]["runs"] if r["solver"] == "cudaq-gpu")
    assert m["feasible"] is None
    assert m["objective"] is None
    assert all(v is None for v in m["timing"].values())
    assert m["attempt_wall_time_seconds"] == 12.0
    assert m["missing_measurements"]["wall_time_seconds"]
    group = next(g for g in result.groups if g.group_key["solver"] == "cudaq-gpu")
    assert group.timing.total_wall_time_seconds.count == 0


def test_no_exact_does_not_turn_best_observed_into_optimum(baseline):
    h = variant(baseline)
    result = analysis([h])
    assert result.instances[0]["reference_optimum"] is None
    assert result.instances[0]["runs"][0]["optimality_gap_percent"] is None
    assert result.groups[0].quality.mean_gap_percent is None
    assert result.groups[0].quality.success_at_optimum_rate is None


@pytest.mark.parametrize("sense", [OptimizationSense.MAXIMIZE, OptimizationSense.MINIMIZE])
def test_sense_aware_paired_improvement_and_zero_reference(tmp_path, sense):
    problem = SubsetSelectionProblem.from_data(["a"], {"a": 5.0}, sense=sense)
    runner = ExperimentRunner(ExperimentStore(tmp_path / "db"))
    exact = runner.benchmark(problem, [ExactSolver()], {"exact": SolverConfig()})[0]
    solution = (0,) if sense is OptimizationSense.MAXIMIZE else (1,)
    h = variant(exact, solution=solution)
    result = analysis([exact, h])
    assert result.comparisons[0].pairs[0]["objective_improvement_left"] == 5.0
    m = next(r for r in result.instances[0]["runs"] if r["solver"] == "heuristic")
    assert m["optimality_gap"] == 5.0
    assert m["optimality_gap_percent"] == (100.0 if sense is OptimizationSense.MAXIMIZE else None)
    assert best_known_objective([exact])[0] == exact.result.objective


def test_incomplete_timing_and_historical_serialization(baseline):
    h = variant(baseline, solver_time_seconds=None)
    h = replace(
        h,
        environment={},
        result=replace(
            h.result, backend=replace(h.result.backend, metrics={"warmup_seconds": None})
        ),
    )
    old = h.to_dict()
    for field in ("optimality_gap_percent", "normalized_score", "rerun_of"):
        old.pop(field, None)
        old["result"].pop(field, None)
    restored = ExperimentRun.from_dict(old)
    m = analysis([restored]).instances[0]["runs"][0]
    assert m["timing"]["initialization_seconds"] is None
    assert m["timing"]["warmup_seconds"] is None
    assert m["cold_start_verified"] is None
    assert json.loads(json.dumps(m))["timing"]["solver_time_seconds"] is None


def quantum(run, name, seed, values, warmup=False):
    params = {
        "p": 1,
        "shots": 16,
        "optimizer_trials": 2,
        "warmup": warmup,
        "candidate_parameters": [[float(seed), 0.1], [float(seed), 0.2]],
    }
    q = variant(run, name=name, seed=seed, repeat=seed, solution=run.result.solution)
    return replace(
        q,
        solver_config=SolverConfig(seed=seed, parameters=params),
        result=replace(
            q.result,
            parameters=params,
            backend=replace(
                q.result.backend,
                metrics={"candidate_expectations": values, "floating_point_precision": "fp64"},
            ),
        ),
    )


def test_numerical_equivalence_is_paired_by_repeat(baseline):
    runs = [
        quantum(baseline, name, seed, [seed * 10.0, seed * 10.0 + 1])
        for seed in (1, 2)
        for name in ("qaoa", "cudaq-cpu")
    ]
    result = quantum_comparison_json_data(MaxCutProblem.from_dict(baseline.problem), runs)
    assert result["comparison"]["max_expectation_delta"] == 0.0
    assert result["comparison"]["expectation_comparison_count"] == 2
    assert len(result["comparison"]["paired_repeats"]) == 2
    single = quantum_comparison_json_data(MaxCutProblem.from_dict(baseline.problem), runs[:1])
    assert single["comparison"]["max_expectation_delta"] is None


@pytest.mark.parametrize("change", ["budget", "expectations", "warmup", "seed", "candidates"])
def test_incomplete_or_unmatched_quantum_controls(baseline, change):
    left = quantum(baseline, "qaoa", 1, [1.0, 2.0])
    right = quantum(baseline, "cudaq-cpu", 1, [1.0, 2.0])
    params = dict(right.solver_config.parameters)
    if change == "budget":
        params["shots"] = 32
    elif change == "warmup":
        params["warmup"] = True
    elif change == "candidates":
        params["candidate_parameters"] = [[0.0, 0.1], [0.0, 0.2]]
    elif change == "expectations":
        right = replace(
            right, result=replace(right.result, backend=replace(right.result.backend, metrics={}))
        )
    right = replace(
        right, solver_config=SolverConfig(seed=2 if change == "seed" else 1, parameters=params)
    )
    n = analysis([left, right]).comparisons[0].pairs[0]["numerical_correctness"]
    assert n["max_expectation_delta"] is None
    assert n["reason"]


def test_variability_separates_warmup_modes(baseline):
    cold = quantum(baseline, "qaoa", 1, [1.0, 2.0])
    warm = quantum(baseline, "qaoa", 2, [1.0, 2.0], warmup=True)
    repeats = analysis([cold, warm]).instances[0]["repeats"]
    assert {r["warmup_mode"] for r in repeats} == {"unwarmed", "explicit_warmup"}
    assert all(r["objective"]["std"] is None for r in repeats)


def test_repeat_statistics_count_missing_observations(baseline):
    a = variant(baseline, wall_time_seconds=1.0, solver_time_seconds=None)
    b = variant(baseline, repeat=1, seed=43, wall_time_seconds=3.0)
    r = analysis([a, b]).instances[0]["repeats"][0]
    assert r["timing"]["wall_time_seconds"]["mean"] == 2.0
    assert r["timing"]["wall_time_seconds"]["std"] == pytest.approx(2**0.5)
    assert r["timing"]["solver_time_seconds"]["count"] == 1


@pytest.mark.parametrize("empty", [False, True])
def test_exports_are_stable_and_include_paired_csv(tmp_path, baseline, empty):
    result = analysis([] if empty else [baseline, variant(baseline)])
    report = generate_report(result)
    paths = export_report(report, tmp_path / "reports")
    assert {"runs", "pairs", "repeats"} <= paths["csv"].keys()
    assert json.loads(Path(paths["json"]).read_text())["report_format_version"] == "1"
    for name in ("runs", "pairs", "repeats"):
        with Path(paths["csv"][name]).open() as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames
            assert bool(list(reader)) is not empty
    old = {
        p: Path(p).read_bytes() for p in (paths["json"], paths["markdown"], *paths["csv"].values())
    }
    export_report(report, tmp_path / "reports", overwrite=True)
    assert all(Path(p).read_bytes() == content for p, content in old.items())
    legacy = analyze_runs([], AnalysisQuery())
    assert generate_report(legacy).report_id != report.report_id


def test_campaign_reruns_and_skips(tmp_path, monkeypatch):
    store = ExperimentStore(tmp_path / "db")
    campaign_store = CampaignStore(tmp_path / "db")
    campaign = ExperimentCampaign(
        name="tiny",
        family="maxcut",
        problem_sizes=(3,),
        problem_seeds=(1,),
        solvers=("exact", "heuristic"),
        repeats=2,
    )
    runner = CampaignRunner(ExperimentRunner(store), campaign_store, tmp_path / "problems")
    first = runner.run(campaign)
    second = runner.run(campaign)
    assert first["campaign_id"] == second["campaign_id"]
    assert set(first["run_ids"]).isdisjoint(second["run_ids"])
    assert len(campaign_store.get_run_ids(first["campaign_id"])) == 8
    monkeypatch.setattr(
        "variaq.campaigns.runner.get_solver",
        lambda name: ExactSolver() if name == "exact" else replace_solver_families(),
    )
    skipped = runner.run(replace(campaign, name="skip"))
    assert skipped["status_summary"]["skipped"] == 2
    assert skipped["completed_runs"] == 2


def replace_solver_families():
    solver = ExactSolver()
    solver.name = "heuristic"
    solver.supported_families = frozenset()
    return solver


@pytest.mark.parametrize("missing", [True, False])
def test_missing_packages_and_gpu_are_unavailable(tmp_path, monkeypatch, missing):
    solver = ExactSolver()
    solver.name = "cudaq-gpu"

    def unavailable(problem, config):
        if missing:
            raise MissingOptionalDependency("Install CUDA-Q")
        raise BackendUnavailableError("No GPU", backend_name="nvidia", provider="cudaq")

    monkeypatch.setattr(solver, "solve", unavailable)
    run = ExperimentRunner(ExperimentStore(tmp_path / "db")).run_one(
        MaxCutProblem.generate(3, 0.4, 1), solver, SolverConfig()
    )
    assert run.result.status is SolveStatus.UNAVAILABLE
    assert run.result.solver_time_seconds is None
    assert run.result.backend.metrics["reason"]


def test_opt_in_suite_bounds_and_deterministic_identity():
    root = Path(__file__).resolve().parents[1]
    for mode in ("unwarmed", "warmed"):
        campaign = ExperimentCampaign.from_dict(
            json.loads((root / f"benchmarks/maxcut_v0.8_{mode}.campaign.json").read_text())
        )
        assert campaign.requested_runs == 90
        assert max(campaign.problem_sizes) == 8
        assert campaign.solver_config["exact"].parameters["max_states"] == 256
        assert campaign_definition_id(campaign) == campaign_definition_id(
            replace(campaign, created_at="later")
        )


def test_full_matrix_without_optional_candidate_dependencies(tmp_path, monkeypatch):
    def missing_numpy():
        raise MissingOptionalDependency("NumPy is absent")

    monkeypatch.setattr("variaq.solvers.qaoa_shared._numpy", missing_numpy)
    root = Path(__file__).resolve().parents[1]
    campaign = ExperimentCampaign.from_dict(
        json.loads((root / "benchmarks/maxcut_v0.8_unwarmed.campaign.json").read_text())
    )
    campaign = replace(campaign, problem_sizes=(4,), problem_seeds=(11,), repeats=1)
    runner = CampaignRunner(
        ExperimentRunner(ExperimentStore(tmp_path / "db")),
        CampaignStore(tmp_path / "db"),
        tmp_path / "problems",
    )
    summary = runner.run(campaign)
    assert summary["completed_runs"] == 5
    assert summary["status_summary"]["success"] == 2
    assert summary["status_summary"]["unavailable"] == 3


def test_gpu_precision_options_and_target_restoration():
    class TargetRecorder:
        def __init__(self):
            self.original = object()
            self.calls = []

        def get_target(self):
            return self.original

        def set_target(self, target, **options):
            self.calls.append((target, options))

    recorder = TargetRecorder()
    with pytest.raises(RuntimeError, match="failed"):
        with _selected_target(recorder, "nvidia", "fp64"):
            raise RuntimeError("failed")
    assert recorder.calls == [("nvidia", {"option": "fp64"}), (recorder.original, {})]


def test_cli_schema_one_paired_analysis_and_report(tmp_path):
    definition = ExperimentCampaign(
        name="cli",
        family="maxcut",
        problem_sizes=(3,),
        problem_seeds=(1,),
        solvers=("exact", "heuristic"),
    )
    config = tmp_path / "campaign.json"
    config.write_text(json.dumps(definition.to_dict()))
    base = ["--db", str(tmp_path / "db"), "--problems-dir", str(tmp_path / "problems")]
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([*base, "campaign", "run", str(config), "--json"]) == 0
    campaign_id = json.loads(output.getvalue())["data"]["campaign_id"]
    for command in (
        ["analyze", "campaign", campaign_id, "--compare", "paired_solvers", "--json"],
        [
            "report",
            "campaign",
            campaign_id,
            "--compare",
            "paired_solvers",
            "--output-dir",
            str(tmp_path / "reports"),
            "--json",
        ],
    ):
        output = io.StringIO()
        with redirect_stdout(output):
            assert main([*base, *command]) == 0
        assert json.loads(output.getvalue())["schema_version"] == "1"
