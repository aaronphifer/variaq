"""Per-instance measurements and conservative pairing of persisted solver runs.

No solver is executed here. Solutions are evaluated by their original problem;
only feasible exact results establish an optimum. Timing and numerical agreement
are separate observations, never evidence of quantum advantage.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from itertools import combinations
from typing import Any

from variaq.analysis.metrics import absolute_gap, make_repeat_summary
from variaq.analysis.models import ComparisonSummary
from variaq.errors import VariaQError
from variaq.models import ExperimentRun, SolveStatus
from variaq.problems.base import problem_from_dict
from variaq.solvers.qaoa_shared import QAOA_SOLVER_NAMES, candidate_parameter_digest

TIMING_FIELDS = {
    "wall_time_seconds": None,
    "solver_time_seconds": None,
    "initialization_seconds": "backend_initialization_seconds",
    "warmup_seconds": "warmup_seconds",
    "expectation_evaluation_seconds": "expectation_evaluation_seconds",
    "parameter_search_seconds": "parameter_search_seconds",
    "sampling_seconds": "final_sampling_seconds",
    "first_backend_evaluation_seconds": "first_backend_evaluation_seconds",
}


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def _evaluation(run: ExperimentRun) -> tuple[float | None, bool | None, str | None]:
    if run.result.status is not SolveStatus.SUCCESS or run.result.solution is None:
        return None, None, "No successful solution to evaluate"
    try:
        problem = problem_from_dict(run.problem)
        if problem.problem_id != run.result.problem_id:
            return None, None, "Result and embedded problem IDs differ"
        evaluation = problem.evaluate(run.result.solution)
        return _number(evaluation.objective), evaluation.feasible, None
    except (VariaQError, ValueError, KeyError, TypeError) as exc:
        return None, None, f"Problem evaluation unavailable: {exc}"


def _measurement(run: ExperimentRun, optimum: float | None) -> dict[str, Any]:
    problem = problem_from_dict(run.problem)
    objective, feasible, reason = _evaluation(run)
    missing: dict[str, str] = {}
    if reason:
        missing.update(objective=reason, feasible=reason)
    metrics = run.result.backend.metrics
    timing: dict[str, float | None] = {}
    for field, metric in TIMING_FIELDS.items():
        raw = metrics.get(metric) if metric else getattr(run.result, field)
        value = _number(raw)
        if value is not None and value < 0:
            value = None
        # Failed/unavailable attempt durations are not successful solver performance.
        if run.result.status is not SolveStatus.SUCCESS:
            value = None
        timing[field] = value
        if value is None:
            missing[field] = (
                "No successful solve; attempt wall time is reported separately"
                if run.result.status is not SolveStatus.SUCCESS
                else "Not measured by this solver or absent from historical metadata"
            )
    if (
        run.result.solver_name in QAOA_SOLVER_NAMES
        and run.solver_config.parameters.get("warmup") is False
    ):
        timing["warmup_seconds"] = None
        missing["warmup_seconds"] = "Warmup was not requested"
    gap = (
        absolute_gap(optimum, objective, problem.sense)
        if optimum is not None and objective is not None and feasible
        else None
    )
    percent = (
        gap / abs(optimum) * 100 if gap is not None and optimum else (0.0 if gap == 0 else None)
    )
    if gap is None:
        missing["optimality_gap"] = "No proven reference optimum or no feasible solution"
    if percent is None:
        missing["optimality_gap_percent"] = (
            "Relative gap undefined for a zero optimum"
            if optimum == 0
            else missing["optimality_gap"]
        )
    warmup = run.solver_config.parameters.get("warmup")
    if run.result.solver_name not in QAOA_SOLVER_NAMES:
        mode = "not_applicable"
    elif warmup is True:
        mode = "explicit_warmup"
    elif warmup is False:
        mode = "unwarmed"
    else:
        mode = "unknown"
    protocol = run.environment.get("benchmark_protocol", {})
    precision = (
        metrics.get("floating_point_precision", run.result.parameters.get("precision"))
        if run.result.status is SolveStatus.SUCCESS
        else None
    )
    if precision is None:
        missing["precision"] = "Backend precision was not reported by a successful solve"
    return {
        "run_id": run.run_id,
        "benchmark_id": run.benchmark_id,
        "rerun_of": run.rerun_of,
        "solver": run.result.solver_name,
        "solver_version": run.result.solver_version,
        "status": run.result.status.value,
        "problem_id": run.result.problem_id,
        "sense": problem.sense.value,
        "objective": objective,
        "reported_objective": run.result.objective,
        "objective_matches_reported": (
            math.isclose(objective, run.result.objective, rel_tol=1e-9, abs_tol=1e-9)
            if objective is not None and _number(run.result.objective) is not None
            else None
        ),
        "feasible": feasible,
        "reference_optimum": optimum,
        "optimality_gap": gap,
        "optimality_gap_percent": percent,
        "timing": timing,
        "attempt_wall_time_seconds": _number(run.result.wall_time_seconds),
        "timing_scopes": {
            "wall": metrics.get("wall_time_scope"),
            "solver": metrics.get("solver_time_scope"),
            "initialization": metrics.get("backend_initialization_scope"),
            "first_backend_evaluation": metrics.get("first_backend_evaluation_scope"),
            "first_backend_evaluation_overlaps": metrics.get("first_backend_evaluation_overlaps"),
        },
        "warmup_mode": mode,
        "cold_start_verified": protocol.get("cold_start_verified"),
        "cold_start_reason": protocol.get(
            "cold_start_reason", "No process/device isolation recorded"
        ),
        "repeat_index": protocol.get("repeat_index"),
        "solver_invocation_index": protocol.get("solver_invocation_index"),
        "seed": run.solver_config.seed,
        "parameters": run.solver_config.parameters,
        "backend": run.result.backend.to_dict(),
        "precision": precision,
        "requested_precision": run.solver_config.parameters.get("precision"),
        "backend_available": metrics.get(
            "capability_available", (True if run.result.status is SolveStatus.SUCCESS else None)
        ),
        "environment": run.environment,
        "missing_measurements": missing,
        "warnings": list(run.result.warnings),
        "errors": list(run.result.errors),
    }


def _numerical_comparison(
    left: ExperimentRun | None, right: ExperimentRun | None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "matched_controls": None,
        "max_expectation_delta": None,
        "reason": "Two successful QAOA runs are required",
    }
    if left is None or right is None:
        return result
    if any(r.result.status is not SolveStatus.SUCCESS for r in (left, right)):
        return result
    if any(r.result.solver_name not in QAOA_SOLVER_NAMES for r in (left, right)):
        result["reason"] = "Candidate expectations apply only to QAOA backend comparisons"
        return result
    controls = ("p", "shots", "optimizer_trials", "warmup")
    configs = [r.solver_config for r in (left, right)]
    candidates = [c.parameters.get("candidate_parameters") for c in configs]
    if any(not c for c in candidates) or any(
        c.parameters.get(field) is None for c in configs for field in controls
    ):
        result["reason"] = "Incomplete QAOA controls/candidate metadata"
        return result
    digests = [candidate_parameter_digest(c) for c in candidates]
    matched = (
        digests[0] == digests[1]
        and configs[0].seed == configs[1].seed
        and all(configs[0].parameters[k] == configs[1].parameters[k] for k in controls)
    )
    result["matched_controls"] = matched
    if not matched:
        result["reason"] = "QAOA candidates, budgets, seeds or warmup controls differ"
        return result
    values = [r.result.backend.metrics.get("candidate_expectations") for r in (left, right)]
    if any(not v or len(v) != len(candidates[0]) for v in values):
        result["reason"] = "Incomplete candidate expectations"
        return result
    if any(_number(v) is None for vs in values for v in vs):
        result["reason"] = "Non-finite candidate expectations"
        return result
    result.update(
        max_expectation_delta=max(abs(a - b) for a, b in zip(*values, strict=True)), reason=None
    )
    return result


def paired_analysis(
    runs: list[ExperimentRun],
) -> tuple[tuple[dict[str, Any], ...], ComparisonSummary]:
    """Pair within one benchmark execution/repeat; never zip unrelated histories.

    Old records fall back to configuration seed only within a benchmark ID.
    Duplicate solver slots are ambiguous and remain unpaired. Standalone runs
    still receive measurements, but cannot establish experimental pairing.
    """
    by_problem: dict[str, list[ExperimentRun]] = defaultdict(list)
    for run in runs:
        by_problem[run.result.problem_id].append(run)
    instances: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    warnings: list[str] = []
    for problem_id, instance_runs in sorted(by_problem.items()):
        instance_runs.sort(key=lambda r: r.run_id)
        problem = problem_from_dict(instance_runs[0].problem)
        if any(
            problem_from_dict(r.problem).identity_payload() != problem.identity_payload()
            for r in instance_runs
        ):
            warnings.append(f"{problem_id}: conflicting problem snapshots; pairing refused")
            continue
        exact = [
            obj
            for r in instance_runs
            for obj, feasible, _reason in [_evaluation(r)]
            if r.result.solver_name == "exact" and feasible and obj is not None
        ]
        optimum = exact[0] if exact and len(set(exact)) == 1 else None
        if exact and optimum is None:
            warnings.append(f"{problem_id}: exact references disagree; optimum unavailable")
        measurements = {r.run_id: _measurement(r, optimum) for r in instance_runs}
        repeats: dict[str, list[dict[str, Any]]] = defaultdict(list)
        slots: dict[tuple[str, str], dict[str, list[ExperimentRun]]] = defaultdict(
            lambda: defaultdict(list)
        )
        expected: dict[str, set[str]] = defaultdict(set)
        for r in instance_runs:
            m = measurements[r.run_id]
            params = {k: v for k, v in m["parameters"].items() if k != "candidate_parameters"}
            key = json.dumps(
                [m["solver"], m["backend"]["name"], params, m["warmup_mode"]], sort_keys=True
            )
            repeats[key].append(m)
            if r.benchmark_id is None:
                warnings.append(f"{r.run_id}: no benchmark ID; run is not paired")
                continue
            repeat = m["repeat_index"]
            label = f"repeat:{repeat}" if repeat is not None else f"seed:{r.solver_config.seed}"
            slots[(r.benchmark_id, label)][r.result.solver_name].append(r)
            expected[r.benchmark_id].add(r.result.solver_name)
        repeat_rows = []
        for key, ms in sorted(repeats.items()):
            solver, backend, params, mode = json.loads(key)
            repeat_rows.append(
                {
                    "solver": solver,
                    "backend": backend,
                    "parameters": params,
                    "warmup_mode": mode,
                    "run_ids": [m["run_id"] for m in ms],
                    "status_counts": {
                        s: sum(m["status"] == s for m in ms)
                        for s in ("success", "failed", "unavailable")
                    },
                    "objective": make_repeat_summary(
                        [m["objective"] for m in ms if m["feasible"]]
                    ).to_dict(),
                    "timing": {
                        f: make_repeat_summary([m["timing"][f] for m in ms]).to_dict()
                        for f in TIMING_FIELDS
                    },
                }
            )
        instances.append(
            {
                "problem_id": problem_id,
                "problem": problem.to_dict(),
                "sense": problem.sense.value,
                "reference_optimum": optimum,
                "reference_run_ids": [
                    r.run_id
                    for r in instance_runs
                    if r.result.solver_name == "exact" and _evaluation(r)[1]
                ],
                "reference_reason": None
                if optimum is not None
                else "No consistent feasible exact run in selection",
                "runs": list(measurements.values()),
                "repeats": repeat_rows,
            }
        )
        for (benchmark_id, label), solvers in sorted(slots.items()):
            for a, b in combinations(sorted(expected[benchmark_id]), 2):
                left = solvers[a][0] if len(solvers[a]) == 1 else None
                right = solvers[b][0] if len(solvers[b]) == 1 else None
                lm = measurements[left.run_id] if left else None
                rm = measurements[right.run_id] if right else None
                missing = {
                    name: "No recorded run (skipped, filtered or incomplete execution)"
                    if not solvers[name]
                    else "Ambiguous duplicate solver/repeat slot"
                    for name, r in ((a, left), (b, right))
                    if r is None
                }
                numerical = _numerical_comparison(left, right)
                quality_delta = None
                if lm and rm and lm["feasible"] and rm["feasible"]:
                    quality_delta = lm["objective"] - rm["objective"]
                    if problem.sense.value == "minimize":
                        quality_delta = -quality_delta
                # Raw durations are observations. No speed ratio is inferred, and
                # numerical agreement is independently reported above.
                pairs.append(
                    {
                        "problem_id": problem_id,
                        "benchmark_id": benchmark_id,
                        "repeat_key": label,
                        "left_solver": a,
                        "right_solver": b,
                        "left_run_id": left.run_id if left else None,
                        "right_run_id": right.run_id if right else None,
                        "objective_improvement_left": quality_delta,
                        "numerical_correctness": numerical,
                        "missing_pairs": missing,
                        "left": {
                            k: lm[k]
                            for k in (
                                "status",
                                "objective",
                                "feasible",
                                "timing",
                                "warmup_mode",
                                "seed",
                                "precision",
                            )
                        }
                        if lm
                        else None,
                        "right": {
                            k: rm[k]
                            for k in (
                                "status",
                                "objective",
                                "feasible",
                                "timing",
                                "warmup_mode",
                                "seed",
                                "precision",
                            )
                        }
                        if rm
                        else None,
                    }
                )
    return tuple(instances), ComparisonSummary(
        "paired_solvers", pairs, tuple(sorted(set(warnings)))
    )
