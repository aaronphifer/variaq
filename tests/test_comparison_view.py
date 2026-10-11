"""Derived UI summaries must preserve authoritative zero/null and group identity."""

from copy import deepcopy

import pytest

from variaq.analysis.comparison_view import comparison_view
from variaq.analysis.paired import TIMING_FIELDS


def measurement(run_id, *, objective=6.0, gap=0.0, percent=0.0, **changes):
    return {
        "run_id": run_id,
        "solver": "heuristic",
        "solver_version": "1",
        "status": "success",
        "feasible": True,
        "objective": objective,
        "optimality_gap": gap,
        "optimality_gap_percent": percent,
        "timing": dict.fromkeys(TIMING_FIELDS, 0.0),
        "timing_scopes": {"wall": "complete_call", "solver": "compute"},
        "backend": {"name": "cpu", "versions": {}, "metrics": {}},
        "parameters": {"restarts": 4, "candidate_parameters": [[0.5, 0.2]]},
        "precision": "fp64",
        "warmup_mode": "not_applicable",
        "benchmark_id": "bench-1",
        "environment": {"platform": "test", "benchmark_protocol": {"repeat_index": 0}},
        **changes,
    }


def instance(runs, optimum=6.0, problem_id="problem-1"):
    return {"problem_id": problem_id, "reference_optimum": optimum, "runs": runs}


def test_zero_means_measured_zero_and_valid_denominator():
    valid = [measurement("a"), measurement("b")]
    failed = measurement(
        "failed", status="failed", objective=None, feasible=None, gap=None, percent=None
    )
    infeasible = measurement("infeasible", feasible=False, objective=99, gap=None, percent=None)
    nonfinite = measurement("nan", objective=float("nan"), gap=None, percent=None)
    result = comparison_view((instance([*valid, failed, infeasible, nonfinite]),))[0]
    assert result["valid_run_ids"] == ["a", "b"]
    assert result["excluded_run_count"] == 3
    assert result["reference_comparable_count"] == 2
    assert result["optimum_achieved_count"] == 2
    assert result["optimum_achievement_rate"] == 1.0
    assert result["gap_state"] == "all_zero"
    assert result["gap_counts"] == {"zero": 2, "nonzero": 0, "unavailable": 3}
    assert result["gap_percent"]["mean"] == 0.0
    assert result["timing"]["wall_time_seconds"]["count"] == 2
    assert result["timing"]["wall_time_seconds"]["mean"] == 0.0


def test_missing_reference_does_not_hide_valid_objectives_or_invent_rate():
    result = comparison_view((instance([measurement("a", gap=None, percent=None)], optimum=None),))[
        0
    ]
    assert result["objective"]["mean"] == 6.0
    assert result["valid_run_count"] == 1
    assert result["reference_comparable_count"] == 0
    assert result["optimum_achievement_rate"] is None
    assert result["gap_percent"]["mean"] is None
    assert result["gap_state"] == "unavailable"


def test_zero_reference_with_undefined_relative_gap_still_has_valid_achievement():
    runs = [
        measurement("optimal", objective=0),
        measurement("other", objective=2, gap=2, percent=None),
    ]
    result = comparison_view((instance(runs, optimum=0),))[0]
    assert result["optimum_achievement_rate"] == 0.5
    assert result["reference_comparable_count"] == 2
    assert result["gap_percent"]["count"] == 1
    assert result["gap_counts"] == {"zero": 1, "nonzero": 0, "unavailable": 1}


def test_nonzero_and_unavailable_remain_distinct_without_changing_measurements():
    runs = [
        measurement("zero"),
        measurement("gap", objective=3, gap=3, percent=50),
        measurement("null", gap=None, percent=None),
    ]
    source = deepcopy(runs)
    result = comparison_view((instance(runs),))[0]
    assert runs == source
    assert result["gap_counts"] == {"zero": 1, "nonzero": 1, "unavailable": 1}
    assert result["gap_percent"]["mean"] == 25
    assert result["optimum_achievement_rate"] == 0.5
    assert result["gap_state"] == "nonzero"


@pytest.mark.parametrize(
    "change",
    [
        {"parameters": {"restarts": 9}},
        {"precision": "fp32"},
        {"benchmark_id": "other"},
        {"timing_scopes": {"wall": None, "solver": None}},
        {"environment": {"platform": "another"}},
        {"backend": {"name": "cpu", "versions": {"runtime": "2"}, "metrics": {}}},
        {"warmup_mode": "explicit_warmup"},
    ],
)
def test_incompatible_controls_or_scopes_are_separate_groups(change):
    result = comparison_view((instance([measurement("a"), measurement("b", **change)]),))[0]
    assert len(result["groups"]) == 2
    assert all(len(group["run_ids"]) == 1 for group in result["groups"])


def test_seeds_and_candidates_can_vary_but_problems_never_pool():
    first = measurement("a")
    second = measurement(
        "b",
        parameters={"restarts": 4, "candidate_parameters": [[1, 2]]},
        environment={"platform": "test", "benchmark_protocol": {"repeat_index": 1}},
    )
    result = comparison_view(
        (
            instance([first, second]),
            instance([measurement("c", objective=3, gap=3, percent=50)], problem_id="other"),
        )
    )
    assert len(result) == 2
    assert len(result[0]["groups"]) == 1
    assert result[0]["valid_run_count"] == 2
    assert result[1]["optimum_achievement_rate"] == 0


def test_empty_view_and_empty_instance_have_no_numeric_rate():
    assert comparison_view(()) == []
    result = comparison_view((instance([], optimum=None),))[0]
    assert result["groups"] == []
    assert result["optimum_achievement_rate"] is None
    assert result["gap_state"] == "unavailable"


def test_achievement_keeps_existing_tolerance_without_rounding_gap_to_zero():
    result = comparison_view(
        (instance([measurement("near", objective=6 - 5e-10, gap=5e-10, percent=5e-10 / 6 * 100)]),)
    )[0]
    assert result["optimum_achievement_rate"] == 1
    assert result["gap_counts"] == {"zero": 0, "nonzero": 1, "unavailable": 0}
    assert result["gap_percent"]["mean"] > 0


def test_recorded_gpu_hardware_is_not_pooled_across_devices():
    first = measurement(
        "first", backend={"name": "gpu", "versions": {}, "metrics": {"gpus": [{"name": "one"}]}}
    )
    second = measurement(
        "second", backend={"name": "gpu", "versions": {}, "metrics": {"gpus": [{"name": "two"}]}}
    )
    result = comparison_view((instance([first, second]),))[0]
    assert len(result["groups"]) == 2
