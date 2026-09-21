from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from time import perf_counter
from uuid import uuid4

from variaq.errors import BackendUnavailableError, UnsafeBackendError, ValidationError
from variaq.experiments.storage import ExperimentStore
from variaq.models import (
    BackendMetadata,
    ExperimentRun,
    OptimizationSense,
    SolverConfig,
    SolveResult,
    SolveStatus,
    capture_environment,
    new_run_id,
    utc_now,
)
from variaq.problems.base import ProblemInstance, problem_from_dict
from variaq.solvers.base import Solver, get_solver
from variaq.solvers.qaoa_shared import (
    QAOA_SOLVER_NAMES,
    candidate_parameter_digest,
    common_qaoa_parameters,
    generate_parameter_candidates,
    validate_parameter_candidates,
)


class ExperimentRunner:
    def __init__(self, store: ExperimentStore) -> None:
        self.store = store

    def _execute(
        self,
        problem: ProblemInstance,
        solver: Solver,
        config: SolverConfig,
        benchmark_id: str | None,
        rerun_of: str | None = None,
    ) -> ExperimentRun:
        started = perf_counter()
        try:
            result = solver.solve(problem, config)
            if not result.backend.is_local:
                raise UnsafeBackendError(
                    "VariaQ v0.2 refuses non-local backends; no QPU execution is supported"
                )
        except BackendUnavailableError as exc:
            elapsed = perf_counter() - started
            result = SolveResult(
                solver_name=getattr(solver, "name", type(solver).__name__),
                solver_version=getattr(solver, "version", "unknown"),
                problem_id=problem.problem_id,
                problem_type=problem.problem_type,
                variable_count=problem.variable_count,
                solution=None,
                objective=None,
                feasible=False,
                constraint_violations=(),
                wall_time_seconds=elapsed,
                solver_time_seconds=None,
                backend=BackendMetadata(
                    backend_type="unavailable",
                    name=exc.backend_name,
                    provider=exc.provider,
                    is_local=True,
                    metrics={"capability_available": False, "reason": str(exc)},
                ),
                seed=config.seed,
                parameters=dict(config.parameters),
                timestamp=utc_now(),
                status=SolveStatus.UNAVAILABLE,
                warnings=(str(exc),),
            )
        except Exception as exc:  # Every solver failure must become a durable record.
            elapsed = perf_counter() - started
            result = SolveResult(
                solver_name=getattr(solver, "name", type(solver).__name__),
                solver_version=getattr(solver, "version", "unknown"),
                problem_id=problem.problem_id,
                problem_type=problem.problem_type,
                variable_count=problem.variable_count,
                solution=None,
                objective=None,
                feasible=False,
                constraint_violations=(),
                wall_time_seconds=elapsed,
                solver_time_seconds=None,
                backend=BackendMetadata(
                    backend_type="unavailable",
                    name="not-executed",
                    provider="variaq",
                    is_local=True,
                ),
                seed=config.seed,
                parameters=dict(config.parameters),
                timestamp=utc_now(),
                status=SolveStatus.FAILED,
                errors=(f"{type(exc).__name__}: {exc}",),
            )
        return ExperimentRun(
            run_id=new_run_id(),
            benchmark_id=benchmark_id,
            created_at=utc_now(),
            problem=problem.to_dict(),
            solver_config=config,
            result=result,
            environment=capture_environment(),
            rerun_of=rerun_of,
        )

    @staticmethod
    def _add_comparison(
        run: ExperimentRun,
        problem: ProblemInstance,
        best_known: float | None,
        source: str | None,
    ) -> ExperimentRun:
        result = run.result
        if (
            best_known is None
            or result.status is not SolveStatus.SUCCESS
            or not result.feasible
            or result.objective is None
        ):
            return replace(
                run,
                result=replace(result, best_known_objective=best_known, best_known_source=source),
            )
        if problem.sense is OptimizationSense.MAXIMIZE:
            delta = best_known - result.objective
            gap = max(0.0, delta / abs(best_known) * 100.0) if best_known != 0 else 0.0
            ratio = result.objective / best_known if best_known > 0 else None
            normalized = ratio
        else:
            delta = result.objective - best_known
            gap = max(0.0, delta / abs(best_known) * 100.0) if best_known != 0 else 0.0
            ratio = best_known / result.objective if result.objective > 0 else None
            normalized = ratio
        return replace(
            run,
            result=replace(
                result,
                best_known_objective=best_known,
                best_known_source=source,
                optimality_gap_percent=gap,
                approximation_ratio=ratio,
                normalized_score=normalized,
            ),
        )

    def run_one(
        self,
        problem: ProblemInstance,
        solver: Solver,
        config: SolverConfig,
        *,
        rerun_of: str | None = None,
    ) -> ExperimentRun:
        run = self._execute(problem, solver, config, None, rerun_of)
        if run.result.status is SolveStatus.SUCCESS and solver.name == "exact":
            best_known = run.result.objective
            source = "exact_optimum"
        else:
            best_known = self.store.exact_objective(problem.problem_id)
            source = "stored_exact_optimum" if best_known is not None else None
        run = self._add_comparison(run, problem, best_known, source)
        self.store.save(run)
        return run

    def benchmark(
        self,
        problem: ProblemInstance,
        solvers: Iterable[Solver],
        configs: dict[str, SolverConfig],
        repeats: int = 1,
    ) -> list[ExperimentRun]:
        if repeats < 1:
            raise ValueError("repeats must be positive")
        solver_list = list(solvers)
        benchmark_id = f"benchmark-{uuid4()}"
        pending: list[ExperimentRun] = []
        repeat_configs = [
            self._matched_repeat_configs(problem, solver_list, configs, repeat)
            for repeat in range(repeats)
        ]
        for solver in solver_list:
            for repeat in range(repeats):
                repeat_config = repeat_configs[repeat][solver.name]
                pending.append(self._execute(problem, solver, repeat_config, benchmark_id))

        exact_values = [
            run.result.objective
            for run in pending
            if run.result.solver_name == "exact"
            and run.result.status is SolveStatus.SUCCESS
            and run.result.feasible
            and run.result.objective is not None
        ]
        stored_exact = self.store.exact_objective(problem.problem_id)
        if exact_values:
            best_known = max(exact_values)
            source = "exact_optimum"
        elif stored_exact is not None:
            best_known = stored_exact
            source = "stored_exact_optimum"
        else:
            observed = [
                run.result.objective
                for run in pending
                if run.result.status is SolveStatus.SUCCESS
                and run.result.feasible
                and run.result.objective is not None
            ]
            best_known = max(observed) if observed else None
            source = "best_observed_not_proven_optimal" if observed else None

        completed = [self._add_comparison(run, problem, best_known, source) for run in pending]
        for run in completed:
            self.store.save(run)
        return completed

    @staticmethod
    def _matched_repeat_configs(
        problem: ProblemInstance,
        solvers: list[Solver],
        configs: dict[str, SolverConfig],
        repeat: int,
    ) -> dict[str, SolverConfig]:
        prepared = {
            solver.name: SolverConfig(
                seed=configs.get(solver.name, SolverConfig()).seed + repeat,
                parameters=dict(configs.get(solver.name, SolverConfig()).parameters),
            )
            for solver in solvers
        }
        quantum_names = [solver.name for solver in solvers if solver.name in QAOA_SOLVER_NAMES]
        if len(quantum_names) < 2:
            return prepared

        for name in quantum_names:
            solver = next(s for s in solvers if s.name == name)
            problem_family = problem.family
            if problem_family not in solver.supported_families:
                raise ValidationError(
                    f"Solver {name!r} does not support problem family {problem_family!r}"
                )

        resolved: dict[str, tuple[int, int, int, bool]] = {
            name: common_qaoa_parameters(prepared[name].parameters) for name in quantum_names
        }
        reference_name = quantum_names[0]
        reference = resolved[reference_name]
        reference_seed = prepared[reference_name].seed
        for name in quantum_names[1:]:
            if resolved[name] != reference or prepared[name].seed != reference_seed:
                raise ValidationError(
                    "Matched quantum solvers must use identical p, optimizer_trials, shots, "
                    "warmup, and seed"
                )

        p, optimizer_trials, shots, warmup = reference
        supplied = {
            name: prepared[name].parameters.get("candidate_parameters") for name in quantum_names
        }
        if any(value is not None for value in supplied.values()):
            if any(value is None for value in supplied.values()):
                raise ValidationError(
                    "candidate_parameters must be supplied to every matched quantum solver"
                )
            candidates = validate_parameter_candidates(
                supplied[reference_name], p, optimizer_trials
            )
            reference_digest = candidate_parameter_digest(candidates)
            for name in quantum_names[1:]:
                candidate = validate_parameter_candidates(supplied[name], p, optimizer_trials)
                if candidate_parameter_digest(candidate) != reference_digest:
                    raise ValidationError(
                        "Matched quantum solvers received different candidate parameter vectors"
                    )
        else:
            # Generate once per repeat, then place the identical immutable sequence into
            # every solver configuration and persisted experiment record.
            candidates = generate_parameter_candidates(p, optimizer_trials, reference_seed)

        serialized = [list(candidate) for candidate in candidates]
        for name in quantum_names:
            parameters = dict(prepared[name].parameters)
            parameters.update(
                {
                    "p": p,
                    "optimizer_trials": optimizer_trials,
                    "shots": shots,
                    "warmup": warmup,
                    "candidate_parameters": serialized,
                }
            )
            prepared[name] = SolverConfig(seed=reference_seed, parameters=parameters)
        return prepared

    def reproduce(self, run_id: str) -> ExperimentRun:
        original = self.store.get(run_id)
        problem = problem_from_dict(original.problem)
        solver = get_solver(original.result.solver_name)
        return self.run_one(
            problem,
            solver,
            original.solver_config,
            rerun_of=original.run_id,
        )
