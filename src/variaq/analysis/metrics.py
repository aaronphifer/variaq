"""Domain-neutral statistical and metric helpers for analysis."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from typing import Any

from variaq.analysis.models import RepeatSummary
from variaq.models import ExperimentRun, OptimizationSense, SolveStatus


def _finite(values: Sequence[float | None]) -> list[float]:
    return [float(v) for v in values if v is not None and math.isfinite(float(v))]


def _best(sense: OptimizationSense, values: Sequence[float]) -> float:
    return max(values) if sense is OptimizationSense.MAXIMIZE else min(values)


def _worst(sense: OptimizationSense, values: Sequence[float]) -> float:
    return min(values) if sense is OptimizationSense.MAXIMIZE else max(values)


def make_repeat_summary(values: Sequence[float | None]) -> RepeatSummary:
    finite = _finite(values)
    count = len(finite)
    if count == 0:
        return RepeatSummary(count=0, mean=None, median=None, std=None, minimum=None, maximum=None)
    if count == 1:
        return RepeatSummary(
            count=1,
            mean=finite[0],
            median=finite[0],
            std=None,
            minimum=finite[0],
            maximum=finite[0],
        )
    return RepeatSummary(
        count=count,
        mean=statistics.mean(finite),
        median=statistics.median(finite),
        std=statistics.stdev(finite),
        minimum=min(finite),
        maximum=max(finite),
    )


def best_known_objective(runs: Sequence[ExperimentRun]) -> tuple[float | None, str | None]:
    """Return the best proven/observed objective across the supplied runs."""
    exact = [
        r.result.objective
        for r in runs
        if r.result.solver_name == "exact"
        and r.result.status is SolveStatus.SUCCESS
        and r.result.objective is not None
    ]
    if exact:
        return max(exact), "exact_optimum"
    feasible = [
        r.result.objective
        for r in runs
        if r.result.status is SolveStatus.SUCCESS
        and r.result.feasible
        and r.result.objective is not None
    ]
    if feasible:
        sense = _dominant_sense(runs)
        if sense is OptimizationSense.MAXIMIZE:
            return max(feasible), "best_observed"
        return min(feasible), "best_observed"
    return None, None


def _dominant_sense(runs: Sequence[ExperimentRun]) -> OptimizationSense:
    senses = {r.result.problem_type for r in runs}
    if len(senses) == 1:
        problem_type = next(iter(senses))
        if problem_type == "graph-partition":
            return OptimizationSense.MINIMIZE
    # Default to maximize for historical maxcut-oriented records, but if any problem dict
    # carries an explicit sense, prefer that.
    explicit = set()
    for r in runs:
        sense = r.problem.get("sense")
        if sense:
            explicit.add(sense)
    if len(explicit) == 1:
        s = next(iter(explicit))
        if s == "minimize":
            return OptimizationSense.MINIMIZE
        if s == "maximize":
            return OptimizationSense.MAXIMIZE
    return OptimizationSense.MAXIMIZE


def absolute_gap(best: float, objective: float, sense: OptimizationSense) -> float:
    if sense is OptimizationSense.MAXIMIZE:
        return max(0.0, best - objective)
    return max(0.0, objective - best)


def relative_gap(best: float, objective: float) -> float:
    if best == 0.0:
        return 0.0
    return abs(best - objective) / abs(best) * 100.0


def approximation_ratio(best: float, objective: float, sense: OptimizationSense) -> float | None:
    if sense is OptimizationSense.MAXIMIZE:
        if best == 0.0:
            return None
        return objective / best
    if objective == 0.0:
        return None
    return best / objective


def extract_field(run: ExperimentRun, field: str) -> Any:
    """Extract a normalized value from a run record for grouping/filtering."""
    result = run.result
    if field == "family":
        return result.problem_type
    if field == "problem_id":
        return result.problem_id
    if field == "solver":
        return result.solver_name
    if field == "backend":
        return result.backend.name
    if field == "backend_type":
        return result.backend.backend_type
    if field == "seed":
        return result.seed
    if field == "status":
        return result.status.value
    if field == "feasible":
        return result.feasible
    if field == "qaoa_depth":
        return result.parameters.get("p")
    if field == "shots":
        return result.parameters.get("shots")
    if field == "optimizer_trials":
        return result.parameters.get("optimizer_trials")
    if field == "precision":
        return result.parameters.get("precision")
    if field == "candidate_count":
        return result.parameters.get("optimizer_trials")
    if field == "variaq_version":
        return run.environment.get("packages", {}).get("variaq")
    if field == "qiskit_version":
        return run.environment.get("packages", {}).get("qiskit")
    if field == "cudaq_version":
        return run.environment.get("packages", {}).get("cudaq")
    if field == "python_version":
        return run.environment.get("python", "").split()[0]
    if field.startswith("backend.metrics."):
        key = field.removeprefix("backend.metrics.")
        return result.backend.metrics.get(key)
    if field.startswith("parameters."):
        key = field.removeprefix("parameters.")
        return result.parameters.get(key)
    return None
