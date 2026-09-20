from __future__ import annotations

import random
from time import perf_counter

from variaq.errors import ValidationError
from variaq.models import BackendMetadata, SolverConfig, SolveResult, SolveStatus, utc_now
from variaq.problems.assignment import AssignmentProblem
from variaq.problems.base import ProblemInstance
from variaq.problems.graph_partition import GraphPartitionProblem
from variaq.problems.maxcut import MaxCutProblem
from variaq.problems.subset_selection import SubsetSelectionProblem
from variaq.solvers.base import Solver


class HeuristicSolver(Solver):
    name = "heuristic"
    version = "2"
    supported_families = frozenset({"maxcut", "assignment", "subset-selection", "graph-partition"})

    def solve(self, problem: ProblemInstance, config: SolverConfig) -> SolveResult:
        self.check_family(problem)
        self.validate_parameters(config.parameters, {"restarts", "max_passes"})
        restarts = int(config.parameters.get("restarts", 16))
        max_passes = int(config.parameters.get("max_passes", max(10, problem.variable_count * 4)))
        if restarts < 1 or max_passes < 1:
            raise ValidationError("restarts and max_passes must be positive")

        rng = random.Random(config.seed)
        started = perf_counter()
        best_solution: tuple[int, ...] | None = None
        best_objective: float | None = None
        total_passes = 0

        for restart in range(restarts):
            current = self._initial_solution(problem, rng, restart)
            current_evaluation = problem.evaluate(current)
            current_objective = current_evaluation.objective
            if current_objective is None:
                current_objective = (
                    float("-inf") if problem.sense.value == "maximize" else float("inf")
                )

            for _ in range(max_passes):
                total_passes += 1
                move, delta = self._best_move(problem, current, current_objective)
                if move is None:
                    break
                current = self._apply_move(current, move, problem)
                current_objective += delta

            candidate = tuple(current)
            evaluation = problem.evaluate(candidate)
            if evaluation.feasible and evaluation.objective is not None:
                if best_objective is None or self._compare(
                    problem.sense, evaluation.objective, best_objective
                ):
                    best_objective = evaluation.objective
                    best_solution = candidate
                elif evaluation.objective == best_objective and (
                    best_solution is None or candidate < best_solution
                ):
                    best_solution = candidate

        elapsed = perf_counter() - started
        if best_solution is None:
            # Fallback: return initial random feasible if any; otherwise mark failed.
            return SolveResult(
                solver_name=self.name,
                solver_version=self.version,
                problem_id=problem.problem_id,
                problem_type=problem.problem_type,
                variable_count=problem.variable_count,
                solution=None,
                objective=None,
                feasible=False,
                constraint_violations=("no feasible solution found in heuristic search",),
                wall_time_seconds=float(elapsed),
                solver_time_seconds=float(elapsed),
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
                status=SolveStatus.FAILED,
            )
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

    def _initial_solution(
        self, problem: ProblemInstance, rng: random.Random, restart: int
    ) -> list[int]:
        n = problem.variable_count
        if restart == 0:
            if isinstance(problem, MaxCutProblem):
                return [index % 2 for index in range(n)]
            if isinstance(problem, AssignmentProblem):
                return self._greedy_assignment(problem)
            if isinstance(problem, SubsetSelectionProblem):
                return self._greedy_subset(problem, rng)
            if isinstance(problem, GraphPartitionProblem):
                return self._greedy_partition(problem)
        return [rng.randrange(2) for _ in range(n)]

    @staticmethod
    def _compare(sense, candidate: float, best: float) -> bool:
        if sense.value == "maximize":
            return candidate > best
        return candidate < best

    # Family-specific initializers
    @staticmethod
    def _greedy_assignment(problem: AssignmentProblem) -> list[int]:
        # Greedy assignment by score per task, respecting capacities and avoiding prohibited.
        solution = [0] * problem.variable_count
        resource_count = len(problem.resource_ids)
        resource_loads: dict[str, int] = {resource: 0 for resource in problem.resource_ids}
        for task_index, task in enumerate(problem.task_ids):
            demand_remaining = problem.demand.get(task, 1)
            ranked = sorted(
                (
                    (resource, problem.score.get((task, resource), 0.0))
                    for resource in problem.resource_ids
                    if (task, resource) not in problem.prohibited
                ),
                key=lambda item: item[1],
                reverse=problem.sense.value == "maximize",
            )
            for resource, _ in ranked:
                if demand_remaining <= 0:
                    break
                cap = problem.capacity.get(resource)
                if cap is not None and resource_loads[resource] >= cap:
                    continue
                resource_index = problem.resource_ids.index(resource)
                solution[task_index * resource_count + resource_index] = 1
                resource_loads[resource] += 1
                demand_remaining -= 1
        return solution

    def _greedy_subset(self, problem: SubsetSelectionProblem, rng: random.Random) -> list[int]:
        # Start from an empty subset and greedily add candidates by value density.
        selected: set[str] = set()
        budget_remaining = problem.budget
        candidates = list(problem.candidate_ids)
        rng.shuffle(candidates)
        scored = sorted(
            candidates,
            key=lambda c: problem.score.get(c, 0.0) / max(problem.cost.get(c, 1.0), 1e-9),
            reverse=problem.sense.value == "maximize",
        )
        for candidate in scored:
            cost = problem.cost.get(candidate, 1.0)
            if budget_remaining is not None and cost > budget_remaining:
                continue
            if problem.max_cardinality is not None and len(selected) >= problem.max_cardinality:
                break
            selected.add(candidate)
            if budget_remaining is not None:
                budget_remaining -= cost
        return [1 if c in selected else 0 for c in problem.candidate_ids]

    @staticmethod
    def _greedy_partition(problem: GraphPartitionProblem) -> list[int]:
        # Round-robin initial balanced partition assignment.
        solution = [0] * problem.variable_count
        partition_sizes = {p: 0 for p in range(problem.partition_count)}
        for node_index, _ in enumerate(problem.node_ids):
            # pick smallest partition
            partition = min(partition_sizes, key=lambda p: partition_sizes[p])
            solution[node_index * problem.partition_count + partition] = 1
            partition_sizes[partition] += 1
        return solution

    # Local-search move primitives
    def _best_move(
        self, problem: ProblemInstance, current: list[int], current_objective: float
    ) -> tuple[tuple[int, ...] | None, float]:
        if isinstance(problem, MaxCutProblem):
            return self._best_flip_move(problem, current, current_objective)
        if isinstance(problem, AssignmentProblem):
            return self._best_assignment_move(problem, current)
        if isinstance(problem, SubsetSelectionProblem):
            return self._best_subset_move(problem, current)
        if isinstance(problem, GraphPartitionProblem):
            return self._best_partition_move(problem, current)
        raise ValidationError(f"Unsupported problem family for heuristic: {problem.family}")

    def _best_flip_move(
        self, problem: MaxCutProblem, current: list[int], current_objective: float
    ) -> tuple[tuple[int, ...] | None, float]:
        best_gain = 0.0
        best_index: int | None = None
        for index in range(problem.variable_count):
            current[index] ^= 1
            evaluation = problem.evaluate(current)
            current[index] ^= 1
            if evaluation.feasible and evaluation.objective is not None:
                gain = evaluation.objective - current_objective
                if gain > best_gain or (
                    gain == best_gain and (best_index is None or index < best_index)
                ):
                    best_gain = gain
                    best_index = index
        if best_index is None:
            return None, 0.0
        return (best_index,), best_gain

    def _best_assignment_move(
        self, problem: AssignmentProblem, current: list[int]
    ) -> tuple[tuple[int, ...] | None, float]:
        best_score_change: float | None = None
        best_move: tuple[int, ...] | None = None
        resource_count = len(problem.resource_ids)
        for task_index, task in enumerate(problem.task_ids):
            for resource_index, resource in enumerate(problem.resource_ids):
                variable_index = task_index * resource_count + resource_index
                if current[variable_index]:
                    continue
                if (task, resource) in problem.prohibited:
                    continue
                # Toggle on and find an assigned resource for this task to toggle off.
                current[variable_index] = 1
                for other_index, _other_resource in enumerate(problem.resource_ids):
                    if other_index == resource_index:
                        continue
                    other_variable = task_index * resource_count + other_index
                    if not current[other_variable]:
                        continue
                    current[other_variable] = 0
                    evaluation = problem.evaluate(current)
                    if evaluation.feasible and evaluation.objective is not None:
                        change = evaluation.objective
                        if best_score_change is None or change > best_score_change:
                            best_score_change = change
                            best_move = (variable_index, other_variable)
                    current[other_variable] = 1
                current[variable_index] = 0
        if best_move is None:
            return None, 0.0
        assert best_score_change is not None
        return best_move, best_score_change

    def _best_subset_move(
        self, problem: SubsetSelectionProblem, current: list[int]
    ) -> tuple[tuple[int, ...] | None, float]:
        best_change: float | None = None
        best_move: tuple[int, ...] | None = None
        for index, _ in enumerate(problem.candidate_ids):
            current[index] ^= 1
            evaluation = problem.evaluate(current)
            if evaluation.feasible and evaluation.objective is not None:
                change = evaluation.objective
                if best_change is None or self._compare(problem.sense, change, best_change):
                    best_change = change
                    best_move = (index,)
            current[index] ^= 1
        if best_move is None:
            return None, 0.0
        assert best_change is not None
        return best_move, best_change

    def _best_partition_move(
        self, problem: GraphPartitionProblem, current: list[int]
    ) -> tuple[tuple[int, ...] | None, float]:
        best_change: float | None = None
        best_move: tuple[int, ...] | None = None
        for node_index, _ in enumerate(problem.node_ids):
            for new_partition in range(problem.partition_count):
                old_partition = self._current_partition(
                    current, node_index, problem.partition_count
                )
                if new_partition == old_partition:
                    continue
                current[node_index * problem.partition_count + old_partition] = 0
                current[node_index * problem.partition_count + new_partition] = 1
                evaluation = problem.evaluate(current)
                if evaluation.feasible and evaluation.objective is not None:
                    change = evaluation.objective
                    if best_change is None or self._compare(problem.sense, change, best_change):
                        best_change = change
                        best_move = (node_index, old_partition, new_partition)
                current[node_index * problem.partition_count + old_partition] = 1
                current[node_index * problem.partition_count + new_partition] = 0
        if best_move is None:
            return None, 0.0
        assert best_change is not None
        return best_move, best_change

    @staticmethod
    def _current_partition(current: list[int], node_index: int, partition_count: int) -> int:
        for partition in range(partition_count):
            if current[node_index * partition_count + partition]:
                return partition
        return 0

    def _apply_move(
        self, current: list[int], move: tuple[int, ...], problem: ProblemInstance
    ) -> list[int]:
        if len(move) == 1:
            index = move[0]
            current[index] ^= 1
        elif len(move) == 2:
            a, b = move
            current[a] = 1
            current[b] = 0
        elif len(move) == 3:
            node_index, old_partition, new_partition = move
            if isinstance(problem, AssignmentProblem):
                pc = len(problem.resource_ids)
            elif isinstance(problem, GraphPartitionProblem):
                pc = problem.partition_count
            else:
                pc = len(current) // max(1, node_index + 1)
            if node_index * pc + old_partition < len(current):
                current[node_index * pc + old_partition] = 0
            if node_index * pc + new_partition < len(current):
                current[node_index * pc + new_partition] = 1
        return current


# Backwards-compatible alias for pre-0.4 imports and tests.
HeuristicMaxCutSolver = HeuristicSolver
