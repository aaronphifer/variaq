from __future__ import annotations

from time import perf_counter

from variaq.errors import SolverLimitError, ValidationError
from variaq.models import BackendMetadata, SolverConfig, SolveResult, SolveStatus, utc_now
from variaq.problems.base import ProblemInstance
from variaq.problems.maxcut import MaxCutProblem
from variaq.solvers.base import Solver


class ExactMaxCutSolver(Solver):
    name = "exact"
    version = "1"
    default_max_variables = 24

    def solve(self, problem: ProblemInstance, config: SolverConfig) -> SolveResult:
        if not isinstance(problem, MaxCutProblem):
            raise ValidationError("The exact v0.1 solver supports MaxCut only")
        self.validate_parameters(config.parameters, {"max_variables"})
        max_variables = int(config.parameters.get("max_variables", self.default_max_variables))
        if max_variables < 1:
            raise ValidationError("max_variables must be positive")
        if problem.variable_count > max_variables:
            raise SolverLimitError(
                f"Exact solve refused {problem.variable_count} variables; "
                f"configured guard is {max_variables}"
            )

        started = perf_counter()
        best_solution: tuple[int, ...] | None = None
        best_objective = float("-inf")
        # Complementary cuts are equivalent, so fix node 0 to partition 0.
        states_evaluated = 1 << max(problem.variable_count - 1, 0)
        for state in range(states_evaluated):
            solution = (0,) + tuple(
                (state >> offset) & 1 for offset in range(problem.variable_count - 1)
            )
            evaluation = problem.evaluate(solution)
            assert evaluation.objective is not None
            if evaluation.objective > best_objective:
                best_objective = evaluation.objective
                best_solution = solution
        elapsed = perf_counter() - started
        assert best_solution is not None
        evaluation = problem.evaluate(best_solution)
        assert evaluation.objective is not None
        return SolveResult(
            solver_name=self.name,
            solver_version=self.version,
            problem_id=problem.problem_id,
            problem_type=problem.problem_type,
            variable_count=problem.variable_count,
            solution=best_solution,
            objective=float(evaluation.objective),
            feasible=evaluation.feasible,
            constraint_violations=evaluation.constraint_violations,
            wall_time_seconds=float(elapsed),
            solver_time_seconds=float(elapsed),
            backend=BackendMetadata(
                backend_type="classical_cpu",
                name="python-enumeration",
                provider="variaq",
                is_local=True,
                metrics={"states_evaluated": states_evaluated, "symmetry_reduction": True},
            ),
            seed=config.seed,
            parameters={"max_variables": max_variables},
            timestamp=utc_now(),
            status=SolveStatus.SUCCESS,
        )
