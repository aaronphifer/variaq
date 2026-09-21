"""Domain-neutral analysis models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AnalysisQuery:
    """User-facing analysis request."""

    campaign_id: str | None = None
    run_ids: tuple[str, ...] = ()
    filters: dict[str, Any] = field(default_factory=dict)
    group_by: tuple[str, ...] = ()
    include_failed: bool = False
    include_unavailable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "run_ids": list(self.run_ids),
            "filters": dict(self.filters),
            "group_by": list(self.group_by),
            "include_failed": self.include_failed,
            "include_unavailable": self.include_unavailable,
        }


@dataclass(frozen=True, slots=True)
class RepeatSummary:
    count: int
    mean: float | None
    median: float | None
    std: float | None
    minimum: float | None
    maximum: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "mean": self.mean,
            "median": self.median,
            "std": self.std,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


@dataclass(frozen=True, slots=True)
class QualitySummary:
    count: int
    best_objective: float | None
    worst_objective: float | None
    mean_objective: float | None
    median_objective: float | None
    mean_gap_percent: float | None
    success_at_optimum_rate: float | None
    approximation_ratio: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "best_objective": self.best_objective,
            "worst_objective": self.worst_objective,
            "mean_objective": self.mean_objective,
            "median_objective": self.median_objective,
            "mean_gap_percent": self.mean_gap_percent,
            "success_at_optimum_rate": self.success_at_optimum_rate,
            "approximation_ratio": self.approximation_ratio,
        }


@dataclass(frozen=True, slots=True)
class FeasibilitySummary:
    count: int
    feasible_runs: int
    infeasible_runs: int
    feasible_sample_count: int | None
    infeasible_sample_count: int | None
    mean_feasible_rate: float | None
    median_feasible_rate: float | None
    min_feasible_rate: float | None
    max_feasible_rate: float | None
    zero_feasible_runs: int
    best_feasible_objective: float | None
    best_infeasible_energy: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "feasible_runs": self.feasible_runs,
            "infeasible_runs": self.infeasible_runs,
            "feasible_sample_count": self.feasible_sample_count,
            "infeasible_sample_count": self.infeasible_sample_count,
            "mean_feasible_rate": self.mean_feasible_rate,
            "median_feasible_rate": self.median_feasible_rate,
            "min_feasible_rate": self.min_feasible_rate,
            "max_feasible_rate": self.max_feasible_rate,
            "zero_feasible_runs": self.zero_feasible_runs,
            "best_feasible_objective": self.best_feasible_objective,
            "best_infeasible_energy": self.best_infeasible_energy,
        }


@dataclass(frozen=True, slots=True)
class TimingSummary:
    count: int
    total_wall_time_seconds: RepeatSummary
    solver_time_seconds: RepeatSummary
    initialization_seconds: RepeatSummary | None
    expectation_evaluation_seconds: RepeatSummary | None
    sampling_seconds: RepeatSummary | None
    parameter_search_seconds: RepeatSummary | None
    warmup_seconds: RepeatSummary | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "total_wall_time_seconds": self.total_wall_time_seconds.to_dict(),
            "solver_time_seconds": self.solver_time_seconds.to_dict(),
            "initialization_seconds": self.initialization_seconds.to_dict()
            if self.initialization_seconds
            else None,
            "expectation_evaluation_seconds": self.expectation_evaluation_seconds.to_dict()
            if self.expectation_evaluation_seconds
            else None,
            "sampling_seconds": self.sampling_seconds.to_dict() if self.sampling_seconds else None,
            "parameter_search_seconds": self.parameter_search_seconds.to_dict()
            if self.parameter_search_seconds
            else None,
            "warmup_seconds": self.warmup_seconds.to_dict() if self.warmup_seconds else None,
        }


@dataclass(frozen=True, slots=True)
class ResourceSummary:
    count: int
    logical_variables: int | None
    binary_variables: int | None
    auxiliary_variables: int | None
    qubits: int | None
    estimated_statevector_bytes: int | None
    circuit_depth: RepeatSummary | None
    gate_count: RepeatSummary | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "logical_variables": self.logical_variables,
            "binary_variables": self.binary_variables,
            "auxiliary_variables": self.auxiliary_variables,
            "qubits": self.qubits,
            "estimated_statevector_bytes": self.estimated_statevector_bytes,
            "circuit_depth": self.circuit_depth.to_dict() if self.circuit_depth else None,
            "gate_count": self.gate_count.to_dict() if self.gate_count else None,
        }


@dataclass(frozen=True, slots=True)
class ScalingPoint:
    x_metric: str
    x_value: float
    group_key: dict[str, Any]
    count: int
    quality: QualitySummary
    feasibility: FeasibilitySummary
    timing: TimingSummary
    resource: ResourceSummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "x_metric": self.x_metric,
            "x_value": self.x_value,
            "group_key": self.group_key,
            "count": self.count,
            "quality": self.quality.to_dict(),
            "feasibility": self.feasibility.to_dict(),
            "timing": self.timing.to_dict(),
            "resource": self.resource.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class GroupSummary:
    """Analysis summary for one group of runs."""

    group_key: dict[str, Any]
    count: int
    run_ids: tuple[str, ...]
    problem_ids: tuple[str, ...]
    quality: QualitySummary
    feasibility: FeasibilitySummary
    timing: TimingSummary
    resource: ResourceSummary
    environment_versions: dict[str, set[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_key": self.group_key,
            "count": self.count,
            "run_ids": list(self.run_ids),
            "problem_ids": list(self.problem_ids),
            "quality": self.quality.to_dict(),
            "feasibility": self.feasibility.to_dict(),
            "timing": self.timing.to_dict(),
            "resource": self.resource.to_dict(),
            "environment_versions": {k: sorted(v) for k, v in self.environment_versions.items()},
        }


@dataclass(frozen=True, slots=True)
class ComparisonSummary:
    """Structured comparison of solvers/backends on matched problems."""

    comparison_type: str
    pairs: list[dict[str, Any]]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparison_type": self.comparison_type,
            "pairs": list(self.pairs),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Full result of an analysis query."""

    query: AnalysisQuery
    groups: tuple[GroupSummary, ...]
    scaling_points: tuple[ScalingPoint, ...]
    comparisons: tuple[ComparisonSummary, ...]
    warnings: tuple[str, ...]
    source_run_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query.to_dict(),
            "groups": [g.to_dict() for g in self.groups],
            "scaling_points": [s.to_dict() for s in self.scaling_points],
            "comparisons": [c.to_dict() for c in self.comparisons],
            "warnings": list(self.warnings),
            "source_run_ids": list(self.source_run_ids),
        }
