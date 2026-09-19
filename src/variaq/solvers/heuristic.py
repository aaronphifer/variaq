from __future__ import annotations

import random
from time import perf_counter

from variaq.errors import ValidationError
from variaq.models import BackendMetadata, SolverConfig, SolveResult, SolveStatus, utc_now
from variaq.problems.base import ProblemInstance
from variaq.problems.maxcut import MaxCutProblem
from variaq.solvers.base import Solver


class HeuristicMaxCutSolver(Solver):
    name = "heuristic"
    version = "1"

    def solve(self, problem: ProblemInstance, config: SolverConfig) -> SolveResult:
        if not isinstance(problem, MaxCutProblem):
            raise ValidationError("The heuristic v0.1 solver supports MaxCut only")
        self.validate_parameters(config.parameters, {"restarts", "max_passes"})
        restarts = int(config.parameters.get("restarts", 16))
        max_passes = int(config.parameters.get("max_passes", max(10, problem.variable_count * 4)))
        if restarts < 1 or max_passes < 1:
            raise ValidationError("restarts and max_passes must be positive")

        rng = random.Random(config.seed)
        started = perf_counter()
        best_solution: tuple[int, ...] | None = None
        best_objective = float("-inf")
        total_passes = 0

        for restart in range(restarts):
            if restart == 0:
                current = [index % 2 for index in range(problem.variable_count)]
            else:
                current = [rng.randrange(2) for _ in range(problem.variable_count)]
            current_objective = problem.evaluate(current).objective
            assert current_objective is not None

            for _ in range(max_passes):
                total_passes += 1
                candidates: list[tuple[float, int]] = []
                for index in range(problem.variable_count):
                    current[index] ^= 1
                    candidate_objective = problem.evaluate(current).objective
                    current[index] ^= 1
                    assert candidate_objective is not None
                    candidates.append((candidate_objective - current_objective, index))
                gain, index = max(candidates, key=lambda item: (item[0], -item[1]))
                if gain <= 0:
                    break
                current[index] ^= 1
                current_objective += gain

            candidate = tuple(current)
            if current_objective > best_objective or (
                current_objective == best_objective
                and (best_solution is None or candidate < best_solution)
            ):
                best_objective = current_objective
                best_solution = candidate

        elapsed = perf_counter() - started
        assert best_solution is not None
        evaluation = problem.evaluate(best_solution)
        return SolveResult(
            solver_name=self.name,
            solver_version=self.version,
            problem_id=problem.problem_id,
            problem_type=problem.problem_type,
            variable_count=problem.variable_count,
            solution=best_solution,
            objective=evaluation.objective,
            feasible=evaluation.feasible,
            constraint_violations=evaluation.constraint_violations,
            wall_time_seconds=elapsed,
            solver_time_seconds=elapsed,
            backend=BackendMetadata(
                backend_type="classical_cpu",
                name="seeded-multistart-local-search",
                provider="variaq",
                is_local=True,
                metrics={"restarts": restarts, "passes": total_passes},
            ),
            seed=config.seed,
            parameters={"restarts": restarts, "max_passes": max_passes},
            timestamp=utc_now(),
            status=SolveStatus.SUCCESS,
        )
