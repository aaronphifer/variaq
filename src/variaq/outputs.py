"""Shared helpers for turning VariaQ run records into public JSON shapes."""

from __future__ import annotations

from typing import Any

from variaq.models import ExperimentRun, SolveResult, SolveStatus
from variaq.serialization import OUTPUT_SCHEMA_VERSION, StructuredWarning


def run_summary(run: ExperimentRun) -> dict[str, Any]:
    result = run.result
    data: dict[str, Any] = {
        "run_id": run.run_id,
        "benchmark_id": run.benchmark_id,
        "problem_id": result.problem_id,
        "solver": result.solver_name,
        "status": result.status.value,
        "objective": result.objective,
        "best_known_objective": result.best_known_objective,
        "optimality_gap_percent": result.optimality_gap_percent,
        "approximation_ratio": result.approximation_ratio,
        "wall_time_seconds": result.wall_time_seconds,
        "backend": result.backend.name,
        "backend_type": result.backend.backend_type,
        "seed": result.seed,
        "created_at": run.created_at,
        "rerun_of": run.rerun_of,
    }
    return data


def run_detail(run: ExperimentRun) -> dict[str, Any]:
    """Full public run record used by ``runs show`` and reproduction JSON."""
    return run.to_dict()


def solve_json_data(run: ExperimentRun) -> dict[str, Any]:
    result = run.result
    data: dict[str, Any] = {
        "run_id": run.run_id,
        "problem_id": result.problem_id,
        "problem_type": result.problem_type,
        "solver": result.solver_name,
        "backend": result.backend.name,
        "backend_type": result.backend.backend_type,
        "status": result.status.value,
        "solution": list(result.solution) if result.solution is not None else None,
        "objective": result.objective,
        "best_known_objective": result.best_known_objective,
        "best_known_source": result.best_known_source,
        "optimality_gap_percent": result.optimality_gap_percent,
        "approximation_ratio": result.approximation_ratio,
        "feasible": result.feasible,
        "constraint_violations": list(result.constraint_violations),
        "wall_time_seconds": result.wall_time_seconds,
        "solver_time_seconds": result.solver_time_seconds,
        "seed": result.seed,
        "parameters": dict(result.parameters),
        "qaoa_depth": result.parameters.get("p"),
        "shots": result.parameters.get("shots"),
        "optimizer_trials": result.parameters.get("optimizer_trials"),
        "candidate_parameter_digest": result.backend.metrics.get("candidate_parameter_digest"),
        "selected_parameter_index": result.backend.metrics.get("best_parameter_index"),
        "selected_parameters": result.backend.metrics.get("best_parameters"),
        "expectation": result.backend.metrics.get("optimized_expected_objective"),
        "qubit_count": result.backend.metrics.get("qubit_count"),
        "circuit_depth": result.backend.metrics.get("circuit_depth"),
        "gate_count": result.backend.metrics.get("gate_count"),
        "logical_gate_count": result.backend.metrics.get("logical_gate_count"),
        "backend_metadata": result.backend.to_dict(),
        "created_at": run.created_at,
        "environment": run.environment,
        "schema_version": OUTPUT_SCHEMA_VERSION,
    }
    return data


def benchmark_json_data(problem: Any, runs: list[ExperimentRun]) -> dict[str, Any]:
    statuses = {run.result.status for run in runs}
    if statuses == {SolveStatus.SUCCESS}:
        aggregate_status = "success"
    elif SolveStatus.SUCCESS in statuses:
        aggregate_status = "partial"
    else:
        aggregate_status = "error"
    best_known = next(
        (
            run.result.best_known_objective
            for run in runs
            if run.result.best_known_objective is not None
        ),
        None,
    )
    best_source = next(
        (run.result.best_known_source for run in runs if run.result.best_known_source is not None),
        None,
    )
    records = [solve_json_data(run) for run in runs]
    comparison = {
        "aggregate_status": aggregate_status,
        "best_known_objective": best_known,
        "best_known_source": best_source,
        "solver_count": len(runs),
        "successful_count": sum(1 for run in runs if run.result.status is SolveStatus.SUCCESS),
        "failed_count": sum(1 for run in runs if run.result.status is SolveStatus.FAILED),
        "unavailable_count": sum(1 for run in runs if run.result.status is SolveStatus.UNAVAILABLE),
    }
    return {
        "problem": problem.to_dict(),
        "runs": records,
        "comparison": comparison,
    }


def quantum_comparison_json_data(problem: Any, runs: list[ExperimentRun]) -> dict[str, Any]:
    base = benchmark_json_data(problem, runs)
    successful = [run for run in runs if run.result.status is SolveStatus.SUCCESS]
    unavailable = [run for run in runs if run.result.status is SolveStatus.UNAVAILABLE]
    max_delta = 0.0
    identical_candidates = True
    reference_digest: str | None = None
    if successful:
        reference_digest = str(
            successful[0].result.backend.metrics.get("candidate_parameter_digest")
        )
        digests = {
            str(run.result.backend.metrics.get("candidate_parameter_digest")) for run in successful
        }
        identical_candidates = len(digests) <= 1
        reference_expectations = list(
            successful[0].result.backend.metrics.get("candidate_expectations", [])
        )
        for run in successful[1:]:
            candidate = list(run.result.backend.metrics.get("candidate_expectations", []))
            if len(candidate) == len(reference_expectations):
                max_delta = max(
                    max_delta,
                    max(
                        (
                            abs(float(a) - float(b))
                            for a, b in zip(reference_expectations, candidate, strict=True)
                        ),
                        default=0.0,
                    ),
                )
    best_indices = {
        run.result.solver_name: run.result.backend.metrics.get("best_parameter_index")
        for run in successful
    }
    precision_map = {
        run.result.solver_name: run.result.parameters.get("precision")
        for run in successful
        if run.result.parameters.get("precision") is not None
    }
    target_map = {run.result.solver_name: run.result.backend.name for run in runs}
    base["comparison"].update(
        {
            "matched_qaoa": True,
            "qaoa_depth_p": successful[0].result.parameters.get("p") if successful else None,
            "optimizer_trials": successful[0].result.parameters.get("optimizer_trials")
            if successful
            else None,
            "shots": successful[0].result.parameters.get("shots") if successful else None,
            "seed": successful[0].result.seed if successful else None,
            "candidate_parameter_digest": reference_digest,
            "identical_candidate_parameters": identical_candidates,
            "max_expectation_delta": max_delta,
            "best_parameter_indices": best_indices,
            "precision": precision_map,
            "backend_target": target_map,
            "unavailable": [
                {
                    "solver": run.result.solver_name,
                    "reason": run.result.backend.metrics.get(
                        "reason", run.result.warnings[0] if run.result.warnings else "unavailable"
                    ),
                }
                for run in unavailable
            ],
        }
    )
    return base


def reproduction_json_data(original: ExperimentRun, reproduced: ExperimentRun) -> dict[str, Any]:
    def env_summary(run: ExperimentRun) -> dict[str, Any]:
        env = run.environment
        return {
            "python_version": env.get("python", "").split()[0],
            "variaq_version": env.get("packages", {}).get("variaq"),
            "qiskit_version": env.get("packages", {}).get("qiskit"),
            "cudaq_version": env.get("packages", {}).get("cudaq"),
            "platform": env.get("platform"),
        }

    original_summary = env_summary(original)
    new_summary = env_summary(reproduced)
    differences: dict[str, tuple[Any, Any]] = {}
    for key in set(original_summary) | set(new_summary):
        if original_summary.get(key) != new_summary.get(key):
            differences[key] = (original_summary.get(key), new_summary.get(key))

    return {
        "original_run_id": original.run_id,
        "new_run_id": reproduced.run_id,
        "rerun_of": reproduced.rerun_of,
        "lineage": f"{reproduced.run_id} -> rerun_of {original.run_id}",
        "original": {
            "run_id": original.run_id,
            "solver": original.result.solver_name,
            "problem_id": original.result.problem_id,
            "seed": original.solver_config.seed,
            "parameters": original.solver_config.parameters,
            "environment": original_summary,
            "result": {
                "status": original.result.status.value,
                "objective": original.result.objective,
                "backend": original.result.backend.name,
            },
        },
        "new": {
            "run_id": reproduced.run_id,
            "solver": reproduced.result.solver_name,
            "problem_id": reproduced.result.problem_id,
            "seed": reproduced.solver_config.seed,
            "parameters": reproduced.solver_config.parameters,
            "environment": new_summary,
            "result": solve_json_data(reproduced),
        },
        "environment_differences": {
            key: {"original": old_value, "new": new_value}
            for key, (old_value, new_value) in differences.items()
        },
    }


def result_warnings(result: SolveResult) -> tuple[StructuredWarning, ...]:
    warnings: list[StructuredWarning] = []
    for message in result.warnings:
        warnings.append(StructuredWarning(type="solver_warning", message=message))
    return tuple(warnings)


def run_status_for_exit(runs: list[ExperimentRun]) -> int:
    if any(run.result.status is SolveStatus.FAILED for run in runs):
        return 1
    return 0
