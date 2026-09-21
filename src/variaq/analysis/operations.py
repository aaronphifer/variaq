"""Domain-neutral grouping and aggregation of VariaQ run records."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from variaq.analysis.metrics import (
    _best,
    _dominant_sense,
    _worst,
    approximation_ratio,
    best_known_objective,
    extract_field,
    make_repeat_summary,
    relative_gap,
)
from variaq.analysis.models import (
    AnalysisQuery,
    AnalysisResult,
    ComparisonSummary,
    FeasibilitySummary,
    GroupSummary,
    QualitySummary,
    ResourceSummary,
    ScalingPoint,
    TimingSummary,
)
from variaq.models import ExperimentRun, OptimizationSense, SolveStatus


def _applicable_runs(runs: list[ExperimentRun], query: AnalysisQuery) -> list[ExperimentRun]:
    result: list[ExperimentRun] = []
    for run in runs:
        if run.result.status is SolveStatus.FAILED and not query.include_failed:
            continue
        if run.result.status is SolveStatus.UNAVAILABLE and not query.include_unavailable:
            continue
        ok = True
        for field, expected in query.filters.items():
            value = extract_field(run, field)
            if value != expected:
                ok = False
                break
        if ok:
            result.append(run)
    return result


def _group_key(run: ExperimentRun, group_by: tuple[str, ...]) -> dict[str, Any]:
    key: dict[str, Any] = {}
    for field in group_by:
        key[field] = extract_field(run, field)
    return key


def _make_quality(runs: list[ExperimentRun]) -> QualitySummary:
    successful = [
        r for r in runs if r.result.status is SolveStatus.SUCCESS and r.result.objective is not None
    ]
    count = len(successful)
    if count == 0:
        return QualitySummary(
            count=0,
            best_objective=None,
            worst_objective=None,
            mean_objective=None,
            median_objective=None,
            mean_gap_percent=None,
            success_at_optimum_rate=None,
            approximation_ratio=None,
        )
    objectives = [float(r.result.objective) for r in successful]
    sense = _dominant_sense(successful)
    best, source = best_known_objective(successful)
    if best is None:
        best = _best(sense, objectives)
    gaps = [relative_gap(float(best), obj) for obj in objectives]
    successes = [
        1
        for r in successful
        if r.result.best_known_objective is not None
        and r.result.objective is not None
        and abs(float(r.result.objective) - float(r.result.best_known_objective)) <= 1e-9
    ]
    ratios: list[float] = []
    for obj in objectives:
        ratio = approximation_ratio(best, obj, sense)
        if ratio is not None and best is not None:
            ratios.append(float(ratio))
    return QualitySummary(
        count=count,
        best_objective=_best(sense, objectives),
        worst_objective=_worst(sense, objectives),
        mean_objective=sum(objectives) / len(objectives),
        median_objective=sorted(objectives)[len(objectives) // 2] if objectives else None,
        mean_gap_percent=sum(gaps) / len(gaps) if gaps else None,
        success_at_optimum_rate=sum(successes) / len(successful) if successful else None,
        approximation_ratio=sum(ratios) / len(ratios) if ratios else None,
    )


def _make_feasibility(runs: list[ExperimentRun]) -> FeasibilitySummary:
    feasible_runs = [r for r in runs if r.result.feasible]
    infeasible_runs = [r for r in runs if not r.result.feasible]
    feasible_sample_count: int | None = None
    infeasible_sample_count: int | None = None
    rates: list[float] = []
    zero_feasible = 0
    best_feasible: float | None = None
    best_infeasible_energy: float | None = None
    for r in runs:
        fsc = r.result.backend.metrics.get("feasible_sample_count")
        isc = r.result.backend.metrics.get("infeasible_sample_count")
        if fsc is not None:
            feasible_sample_count = (feasible_sample_count or 0) + int(fsc)
        if isc is not None:
            infeasible_sample_count = (infeasible_sample_count or 0) + int(isc)
        if fsc is not None and isc is not None:
            total = int(fsc) + int(isc)
            if total > 0:
                rate = int(fsc) / total
                rates.append(rate)
                if int(fsc) == 0:
                    zero_feasible += 1
        if r.result.feasible and r.result.objective is not None:
            if best_feasible is None:
                best_feasible = float(r.result.objective)
            else:
                sense = _dominant_sense([r])
                if sense is OptimizationSense.MAXIMIZE:
                    best_feasible = max(best_feasible, float(r.result.objective))
                else:
                    best_feasible = min(best_feasible, float(r.result.objective))
        bie = r.result.backend.metrics.get("best_infeasible_energy")
        if bie is not None:
            if best_infeasible_energy is None or float(bie) < float(best_infeasible_energy):
                best_infeasible_energy = float(bie)
    return FeasibilitySummary(
        count=len(runs),
        feasible_runs=len(feasible_runs),
        infeasible_runs=len(infeasible_runs),
        feasible_sample_count=feasible_sample_count,
        infeasible_sample_count=infeasible_sample_count,
        mean_feasible_rate=sum(rates) / len(rates) if rates else None,
        median_feasible_rate=sorted(rates)[len(rates) // 2] if rates else None,
        min_feasible_rate=min(rates) if rates else None,
        max_feasible_rate=max(rates) if rates else None,
        zero_feasible_runs=zero_feasible,
        best_feasible_objective=best_feasible,
        best_infeasible_energy=best_infeasible_energy,
    )


def _make_timing(runs: list[ExperimentRun]) -> TimingSummary:
    wall = make_repeat_summary([r.result.wall_time_seconds for r in runs])
    solver = make_repeat_summary([r.result.solver_time_seconds for r in runs])
    init = make_repeat_summary(
        [r.result.backend.metrics.get("backend_initialization_seconds") for r in runs]
    )
    expect = make_repeat_summary(
        [r.result.backend.metrics.get("expectation_evaluation_seconds") for r in runs]
    )
    sampling = make_repeat_summary(
        [r.result.backend.metrics.get("final_sampling_seconds") for r in runs]
    )
    search = make_repeat_summary(
        [r.result.backend.metrics.get("parameter_search_seconds") for r in runs]
    )
    warmup = make_repeat_summary([r.result.backend.metrics.get("warmup_seconds") for r in runs])
    return TimingSummary(
        count=len(runs),
        total_wall_time_seconds=wall,
        solver_time_seconds=solver,
        initialization_seconds=init if init.count > 0 else None,
        expectation_evaluation_seconds=expect if expect.count > 0 else None,
        sampling_seconds=sampling if sampling.count > 0 else None,
        parameter_search_seconds=search if search.count > 0 else None,
        warmup_seconds=warmup if warmup.count > 0 else None,
    )


def _make_resource(runs: list[ExperimentRun]) -> ResourceSummary:
    logical = next((r.result.variable_count for r in runs), None)
    binary = next((r.result.backend.metrics.get("binary_variable_count") for r in runs), None)
    qubits = next((r.result.backend.metrics.get("qubit_count") for r in runs), None)
    statevector_bytes = next(
        (r.result.backend.metrics.get("estimated_statevector_bytes") for r in runs), None
    )
    depths = make_repeat_summary([r.result.backend.metrics.get("circuit_depth") for r in runs])
    gates = make_repeat_summary([r.result.backend.metrics.get("gate_count") for r in runs])
    return ResourceSummary(
        count=len(runs),
        logical_variables=logical,
        binary_variables=binary,
        auxiliary_variables=None,
        qubits=qubits,
        estimated_statevector_bytes=statevector_bytes,
        circuit_depth=depths if depths.count > 0 else None,
        gate_count=gates if gates.count > 0 else None,
    )


def _make_group(runs: list[ExperimentRun], key: dict[str, Any]) -> GroupSummary:
    env: dict[str, set[str]] = defaultdict(set)
    for r in runs:
        env["variaq"].add(str(r.environment.get("packages", {}).get("variaq")))
        env["qiskit"].add(str(r.environment.get("packages", {}).get("qiskit")))
        env["cudaq"].add(str(r.environment.get("packages", {}).get("cudaq")))
        python_version = r.environment.get("python")
        env["python"].add(str(python_version.split()[0]) if python_version else "")
        env["backend"].add(r.result.backend.name)
    return GroupSummary(
        group_key=key,
        count=len(runs),
        run_ids=tuple(r.run_id for r in runs),
        problem_ids=tuple(sorted({r.result.problem_id for r in runs})),
        quality=_make_quality(runs),
        feasibility=_make_feasibility(runs),
        timing=_make_timing(runs),
        resource=_make_resource(runs),
        environment_versions=dict(env),
    )


def _build_scaling_points(groups: list[GroupSummary], x_metric: str) -> list[ScalingPoint]:
    points: list[ScalingPoint] = []
    for group in groups:
        x_value = group.group_key.get(x_metric)
        if x_value is None or not isinstance(x_value, (int, float)):
            # Try to derive from resource metadata if group key lacks x_metric
            if x_metric in {"problem_size", "logical_variables", "logical"}:
                x_value = group.resource.logical_variables
            elif x_metric in {"binary_variables", "binary"}:
                x_value = group.resource.binary_variables
            elif x_metric in {"qubits", "qubit_count"}:
                x_value = group.resource.qubits
        if x_value is None or not isinstance(x_value, (int, float)):
            continue
        points.append(
            ScalingPoint(
                x_metric=x_metric,
                x_value=float(x_value),
                group_key=group.group_key,
                count=group.count,
                quality=group.quality,
                feasibility=group.feasibility,
                timing=group.timing,
                resource=group.resource,
            )
        )
    return sorted(points, key=lambda p: (p.x_value, str(p.group_key)))


def _classical_vs_quantum(groups: list[GroupSummary]) -> ComparisonSummary:
    pairs: list[dict[str, Any]] = []
    warnings: list[str] = []
    by_problem: dict[str, dict[str, GroupSummary]] = defaultdict(dict)
    for group in groups:
        problem_id = group.group_key.get("problem_id")
        solver = group.group_key.get("solver")
        if problem_id and solver:
            by_problem[str(problem_id)][str(solver)] = group

    for problem_id, solver_groups in by_problem.items():
        exact = solver_groups.get("exact")
        quantum = {s for s in solver_groups if s in {"qaoa", "cudaq-cpu", "cudaq-gpu"}}
        if exact is None:
            if quantum:
                warnings.append(
                    f"Problem {problem_id}: no exact baseline for classical-vs-quantum comparison"
                )
            continue
        row: dict[str, Any] = {"problem_id": problem_id}
        for solver, group in sorted(solver_groups.items()):
            row[solver] = {
                "objective": group.quality.best_objective,
                "gap_percent": group.quality.mean_gap_percent,
                "feasible_rate": group.feasibility.mean_feasible_rate,
                "wall_time_seconds_mean": group.timing.total_wall_time_seconds.mean,
                "run_ids": list(group.run_ids),
            }
        if "qaoa" in solver_groups:
            qaoa = solver_groups["qaoa"]
            row["qaoa_to_exact_gap"] = (
                qaoa.quality.mean_gap_percent if qaoa.quality.mean_gap_percent is not None else None
            )
        pairs.append(row)
    return ComparisonSummary(
        comparison_type="classical_vs_quantum", pairs=pairs, warnings=tuple(warnings)
    )


def _qiskit_vs_cudaq(groups: list[GroupSummary]) -> ComparisonSummary:
    pairs: list[dict[str, Any]] = []
    warnings: list[str] = []
    by_problem: dict[str, dict[str, GroupSummary]] = defaultdict(dict)
    for group in groups:
        problem_id = group.group_key.get("problem_id")
        solver = group.group_key.get("solver")
        if problem_id and solver in {"qaoa", "cudaq-cpu", "cudaq-gpu"}:
            by_problem[str(problem_id)][str(solver)] = group

    for problem_id, solver_groups in by_problem.items():
        if len(solver_groups) < 2:
            continue
        row: dict[str, Any] = {"problem_id": problem_id}
        for solver, group in sorted(solver_groups.items()):
            for _run_id in group.run_ids:
                # backend.metrics expectation is not per-run in summary; use group best
                pass
            row[solver] = {
                "objective": group.quality.best_objective,
                "expectation": group.group_key.get("backend.metrics.optimized_expected_objective"),
                "wall_time_seconds_mean": group.timing.total_wall_time_seconds.mean,
                "run_ids": list(group.run_ids),
            }
            # Fetch first run's backend expectation for comparison
            # This is a lightweight heuristic; detailed comparison can use run records directly.
        pairs.append(row)
    return ComparisonSummary(
        comparison_type="qiskit_vs_cudaq", pairs=pairs, warnings=tuple(warnings)
    )


def _gpu_vs_cpu(groups: list[GroupSummary]) -> ComparisonSummary:
    pairs: list[dict[str, Any]] = []
    by_problem: dict[str, dict[str, GroupSummary]] = defaultdict(dict)
    for group in groups:
        problem_id = group.group_key.get("problem_id")
        solver = group.group_key.get("solver")
        if problem_id and solver in {"cudaq-cpu", "cudaq-gpu"}:
            by_problem[str(problem_id)][str(solver)] = group
    for problem_id, solver_groups in by_problem.items():
        if "cudaq-cpu" in solver_groups and "cudaq-gpu" in solver_groups:
            cpu = solver_groups["cudaq-cpu"]
            gpu = solver_groups["cudaq-gpu"]
            pairs.append(
                {
                    "problem_id": problem_id,
                    "cpu_objective": cpu.quality.best_objective,
                    "gpu_objective": gpu.quality.best_objective,
                    "cpu_wall_time_mean": cpu.timing.total_wall_time_seconds.mean,
                    "gpu_wall_time_mean": gpu.timing.total_wall_time_seconds.mean,
                    "cpu_run_ids": list(cpu.run_ids),
                    "gpu_run_ids": list(gpu.run_ids),
                }
            )
    return ComparisonSummary(comparison_type="gpu_vs_cpu", pairs=pairs, warnings=tuple())


def analyze_runs(
    runs: list[ExperimentRun],
    query: AnalysisQuery,
    *,
    scaling_x_metric: str | None = None,
    comparisons: tuple[str, ...] = (),
) -> AnalysisResult:
    applicable = _applicable_runs(runs, query)
    source_run_ids = tuple(r.run_id for r in applicable)
    warnings: list[str] = []

    if not query.group_by:
        grouped: dict[tuple[tuple[str, Any], ...], list[ExperimentRun]] = {(): applicable}
    else:
        grouped = defaultdict(list)
        for run in applicable:
            key = _group_key(run, query.group_by)
            grouped[tuple(sorted(key.items()))].append(run)

    groups = [_make_group(runs, dict(key)) for key, runs in grouped.items()]
    groups.sort(key=lambda g: str(g.group_key))

    scaling_points: list[ScalingPoint] = []
    if scaling_x_metric:
        scaling_points = _build_scaling_points(groups, scaling_x_metric)

    comparison_results: list[ComparisonSummary] = []
    if "classical_vs_quantum" in comparisons:
        comparison_results.append(_classical_vs_quantum(groups))
    if "qiskit_vs_cudaq" in comparisons:
        comparison_results.append(_qiskit_vs_cudaq(groups))
    if "gpu_vs_cpu" in comparisons:
        comparison_results.append(_gpu_vs_cpu(groups))

    if not applicable:
        warnings.append("No runs matched the analysis query filters/status settings.")

    return AnalysisResult(
        query=query,
        groups=tuple(groups),
        scaling_points=tuple(scaling_points),
        comparisons=tuple(comparison_results),
        warnings=tuple(warnings),
        source_run_ids=source_run_ids,
    )
