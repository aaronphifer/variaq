from __future__ import annotations

from time import perf_counter

from variaq.errors import SolverLimitError, ValidationError
from variaq.models import BackendMetadata, SolverConfig, SolveResult, SolveStatus, utc_now
from variaq.problems.base import ProblemInstance
from variaq.problems.maxcut import MaxCutProblem
from variaq.solvers.base import Solver


class ExactSolver(Solver):
    name = "exact"
    version = "2"
    default_max_states = 1 << 24
    supported_families = frozenset({"maxcut", "assignment", "subset-selection", "graph-partition"})

    def solve(self, problem: ProblemInstance, config: SolverConfig) -> SolveResult:
        self.check_family(problem)
        self.validate_parameters(config.parameters, {"max_states", "max_variables"})
        max_states = int(config.parameters.get("max_states", self.default_max_states))
        if "max_variables" in config.parameters:
            max_states = min(max_states, 1 << int(config.parameters["max_variables"]))
        if max_states < 1:
            raise ValidationError("max_states must be positive")

        started = perf_counter()
        best_solution, best_objective = self._enumerate(problem, max_states)
        elapsed = perf_counter() - started
        evaluation = problem.evaluate(best_solution)
        assert evaluation.objective is not None
        states_evaluated = 1 << min(problem.variable_count, max_states.bit_length() - 1)
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
                metrics={
                    "states_evaluated": states_evaluated,
                    "max_states": max_states,
                    "symmetry_reduction": problem.family == "maxcut",
                },
            ),
            seed=config.seed,
            parameters={"max_states": max_states},
            timestamp=utc_now(),
            status=SolveStatus.SUCCESS,
        )

    def _enumerate(
        self, problem: ProblemInstance, max_states: int
    ) -> tuple[tuple[int, ...], float]:
        n = problem.variable_count
        if n > 63:
            raise SolverLimitError(
                f"Exact enumeration refused {n} variables; exceeds 2^63 safety bound"
            )
        total = 1 << n
        if total > max_states:
            raise SolverLimitError(
                f"Exact enumeration refused {total} states; configured guard is {max_states}"
            )

        best_solution: tuple[int, ...] | None = None
        best_score: float | None = None

        if isinstance(problem, MaxCutProblem):
            # Complementary cuts are equivalent; fix node 0 to partition 0.
            states = 1 << max(n - 1, 0)
            for state in range(states):
                solution = (0,) + tuple((state >> offset) & 1 for offset in range(n - 1))
                evaluation = problem.evaluate(solution)
                if evaluation.feasible and evaluation.objective is not None:
                    if best_score is None or evaluation.objective > best_score:
                        best_score = evaluation.objective
                        best_solution = solution
        else:
            for state in range(total):
                solution = tuple((state >> offset) & 1 for offset in range(n))
                evaluation = problem.evaluate(solution)
                if evaluation.feasible and evaluation.objective is not None:
                    if best_score is None or self._better(
                        problem.sense, evaluation.objective, best_score
                    ):
                        best_score = evaluation.objective
                        best_solution = solution

        if best_solution is None or best_score is None:
            raise SolverLimitError("No feasible solution found during exact enumeration")
        return best_solution, best_score

    @staticmethod
    def _better(sense, candidate: float, best: float) -> bool:
        if sense.value == "maximize":
            return candidate > best
        return candidate < best


# Backwards-compatible alias for pre-0.4 imports and tests.
ExactMaxCutSolver = ExactSolver
