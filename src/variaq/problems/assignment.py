from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from variaq.errors import ValidationError
from variaq.models import Evaluation, OptimizationSense
from variaq.problems.base import ProblemInstance, _identity_hash


@dataclass(frozen=True, slots=True)
class AssignmentProblem(ProblemInstance):
    """Generic assignment of tasks to resources/workers.

    Domain-neutral formulation:
        - tasks: opaque task IDs (must be unique)
        - resources: opaque resource IDs (must be unique)
        - score[task, resource]: utility or cost value (float)
        - prohibited: optional set of (task, resource) pairs that cannot be used
        - capacity[resource]: optional maximum number of tasks that can be assigned
          to a resource (if None, unlimited)
        - demand[task]: optional required number of resources for a task (default 1)

    Canonical objective:
        sum(score[task, resource] * x[task, resource])
        where x[t, r] = 1 if task t is assigned to resource r, else 0.

    Constraints:
        - each task assigned exactly demand[task] times
        - no prohibited pair is selected
        - resource capacities respected

    The natural binary encoding is one variable per (task, resource) pair.
    """

    problem_id: str
    task_ids: tuple[str, ...]
    resource_ids: tuple[str, ...]
    score: dict[tuple[str, str], float]
    prohibited: frozenset[tuple[str, str]]
    capacity: dict[str, int | None]
    demand: dict[str, int]
    generation: dict[str, Any]
    problem_type: str = "assignment"
    family: str = "assignment"
    schema_version: int = 1
    sense: OptimizationSense = OptimizationSense.MAXIMIZE

    def __post_init__(self) -> None:
        if not self.task_ids or not self.resource_ids:
            raise ValidationError("Assignment requires at least one task and one resource")
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValidationError("Duplicate task IDs")
        if len(set(self.resource_ids)) != len(self.resource_ids):
            raise ValidationError("Duplicate resource IDs")
        for task in self.task_ids:
            if self.demand.get(task, 1) < 1:
                raise ValidationError("Task demand must be positive")
        for resource in self.resource_ids:
            cap = self.capacity.get(resource)
            if cap is not None and cap < 0:
                raise ValidationError("Resource capacity must be non-negative")
        seen_pairs: set[tuple[str, str]] = set()
        for (task, resource), _value in self.score.items():
            if task not in set(self.task_ids) or resource not in set(self.resource_ids):
                raise ValidationError(
                    f"Score references unknown task/resource: ({task}, {resource})"
                )
            if (task, resource) in seen_pairs:
                raise ValidationError(f"Duplicate score entry: ({task}, {resource})")
            seen_pairs.add((task, resource))
        for pair in self.prohibited:
            if pair[0] not in set(self.task_ids) or pair[1] not in set(self.resource_ids):
                raise ValidationError(f"Prohibited pair references unknown task/resource: {pair}")
        # Validate that total demand does not exceed total capacity where finite.
        total_demand = sum(self.demand.get(task, 1) for task in self.task_ids)
        total_capacity = sum(
            (self.capacity.get(resource) or 0)
            for resource in self.resource_ids
            if self.capacity.get(resource) is not None
        )
        if total_demand > total_capacity and any(
            self.capacity.get(resource) is not None for resource in self.resource_ids
        ):
            raise ValidationError(
                f"Total demand {total_demand} exceeds total finite capacity {total_capacity}"
            )

    @property
    def variable_count(self) -> int:
        return len(self.task_ids) * len(self.resource_ids)

    def evaluate(self, solution: tuple[int, ...] | list[int]) -> Evaluation:
        resource_count = len(self.resource_ids)
        expected = self.variable_count
        violations: list[str] = []
        if len(solution) != expected:
            violations.append(f"solution length {len(solution)} does not match expected {expected}")
            return Evaluation(
                objective=None, feasible=False, constraint_violations=tuple(violations)
            )
        invalid = [index for index, bit in enumerate(solution) if bit not in (0, 1)]
        if invalid:
            violations.append(f"non-binary values at indices {invalid}")
            return Evaluation(
                objective=None, feasible=False, constraint_violations=tuple(violations)
            )

        # Decode variables: variable index = task_index * resource_count + resource_index
        assignment_counts: dict[str, int] = {task: 0 for task in self.task_ids}
        resource_loads: dict[str, int] = {resource: 0 for resource in self.resource_ids}
        objective = 0.0
        for task_index, task in enumerate(self.task_ids):
            for resource_index, resource in enumerate(self.resource_ids):
                variable_index = task_index * resource_count + resource_index
                if solution[variable_index]:
                    if (task, resource) in self.prohibited:
                        violations.append(f"prohibited assignment: ({task}, {resource})")
                    assignment_counts[task] += 1
                    resource_loads[resource] += 1
                    objective += self.score.get((task, resource), 0.0)

        for task in self.task_ids:
            required = self.demand.get(task, 1)
            if assignment_counts[task] != required:
                violations.append(
                    f"task {task} assigned {assignment_counts[task]} times, expected {required}"
                )
        for resource in self.resource_ids:
            cap = self.capacity.get(resource)
            if cap is not None and resource_loads[resource] > cap:
                violations.append(
                    f"resource {resource} load {resource_loads[resource]} exceeds capacity {cap}"
                )

        feasible = not violations
        return Evaluation(
            objective=float(objective) if feasible else None,
            feasible=feasible,
            constraint_violations=tuple(violations),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "problem_id": self.problem_id,
            "problem_type": self.problem_type,
            "family": self.family,
            "sense": self.sense.value,
            "task_ids": list(self.task_ids),
            "resource_ids": list(self.resource_ids),
            "score": [
                {"task": task, "resource": resource, "value": value}
                for (task, resource), value in sorted(self.score.items())
            ],
            "prohibited": [list(pair) for pair in sorted(self.prohibited)],
            "capacity": {resource: self.capacity.get(resource) for resource in self.resource_ids},
            "demand": {task: self.demand.get(task, 1) for task in self.task_ids},
            "generation": self.generation,
        }

    def identity_payload(self) -> dict[str, Any]:
        return {
            "task_ids": sorted(self.task_ids),
            "resource_ids": sorted(self.resource_ids),
            "score": sorted(
                [
                    {"task": task, "resource": resource, "value": value}
                    for (task, resource), value in self.score.items()
                ],
                key=lambda item: (item["task"], item["resource"]),
            ),
            "prohibited": sorted(self.prohibited),
            "capacity": {
                resource: self.capacity.get(resource) for resource in sorted(self.resource_ids)
            },
            "demand": {task: self.demand.get(task, 1) for task in sorted(self.task_ids)},
            "sense": self.sense.value,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AssignmentProblem:
        if value.get("schema_version") != 1:
            raise ValidationError(
                f"Unsupported assignment schema version: {value.get('schema_version')}"
            )
        try:
            task_ids = tuple(str(task) for task in value["task_ids"])
            resource_ids = tuple(str(resource) for resource in value["resource_ids"])
            score = {
                (str(entry["task"]), str(entry["resource"])): float(entry["value"])
                for entry in value["score"]
            }
            prohibited = frozenset(
                (str(pair[0]), str(pair[1])) for pair in value.get("prohibited", [])
            )
            raw_capacity = value.get("capacity", {})
            capacity = {
                resource: int(raw_capacity[resource])
                if raw_capacity.get(resource) is not None
                else None
                for resource in resource_ids
            }
            raw_demand = value.get("demand", {})
            demand = {task: int(raw_demand.get(task, 1)) for task in task_ids}
            problem = cls(
                problem_id=str(value["problem_id"]),
                task_ids=task_ids,
                resource_ids=resource_ids,
                score=score,
                prohibited=prohibited,
                capacity=capacity,
                demand=demand,
                generation=dict(value.get("generation", {})),
                sense=OptimizationSense(value.get("sense", "maximize")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(f"Invalid assignment document: {exc}") from exc
        expected_id = cls.content_id(problem.identity_payload())
        if problem.problem_id != expected_id:
            raise ValidationError(
                "Problem ID does not match content: "
                f"expected {expected_id}, got {problem.problem_id}"
            )
        return problem

    @classmethod
    def generate(
        cls,
        task_count: int,
        resource_count: int,
        seed: int,
        capacity: int | None = None,
        demand: int = 1,
        prohibited_probability: float = 0.0,
        sense: OptimizationSense = OptimizationSense.MAXIMIZE,
    ) -> AssignmentProblem:
        if task_count < 1 or resource_count < 1:
            raise ValidationError("task_count and resource_count must be positive")
        if not 0.0 <= prohibited_probability <= 1.0:
            raise ValidationError("prohibited_probability must be between 0 and 1")
        rng = random.Random(seed)
        task_ids = tuple(f"task-{index}" for index in range(task_count))
        resource_ids = tuple(f"resource-{index}" for index in range(resource_count))
        score: dict[tuple[str, str], float] = {}
        for task in task_ids:
            for resource in resource_ids:
                score[(task, resource)] = round(rng.uniform(-10.0, 10.0), 4)
        prohibited: set[tuple[str, str]] = set()
        for task in task_ids:
            for resource in resource_ids:
                if rng.random() < prohibited_probability:
                    prohibited.add((task, resource))
        capacities: dict[str, int | None] = {}
        for resource in resource_ids:
            if capacity is None:
                capacities[resource] = None
            else:
                capacities[resource] = max(1, capacity)
        demands = {task: max(1, demand) for task in task_ids}
        identity = {
            "task_ids": sorted(task_ids),
            "resource_ids": sorted(resource_ids),
            "score": sorted(
                [
                    {"task": task, "resource": resource, "value": score[(task, resource)]}
                    for task in task_ids
                    for resource in resource_ids
                ],
                key=lambda item: (item["task"], item["resource"]),
            ),
            "prohibited": sorted(prohibited),
            "capacity": capacities,
            "demand": demands,
            "sense": sense.value,
        }
        return cls(
            problem_id=cls.content_id(identity),
            task_ids=task_ids,
            resource_ids=resource_ids,
            score=score,
            prohibited=frozenset(prohibited),
            capacity=capacities,
            demand=demands,
            generation={
                "method": "random_assignment",
                "task_count": task_count,
                "resource_count": resource_count,
                "capacity": capacity,
                "demand": demand,
                "prohibited_probability": prohibited_probability,
                "seed": seed,
            },
            sense=sense,
        )

    @classmethod
    def from_score_matrix(
        cls,
        task_ids: tuple[str, ...] | list[str],
        resource_ids: tuple[str, ...] | list[str],
        scores: dict[tuple[str, str], float],
        *,
        prohibited: set[tuple[str, str]] | frozenset[tuple[str, str]] | None = None,
        capacity: dict[str, int | None] | None = None,
        demand: dict[str, int] | None = None,
        sense: OptimizationSense = OptimizationSense.MAXIMIZE,
    ) -> AssignmentProblem:
        task_ids = tuple(task_ids)
        resource_ids = tuple(resource_ids)
        demand = dict(demand) if demand else {task: 1 for task in task_ids}
        capacity = dict(capacity) if capacity else {resource: None for resource in resource_ids}
        prohibited = frozenset(prohibited or ())
        identity = {
            "task_ids": sorted(task_ids),
            "resource_ids": sorted(resource_ids),
            "score": sorted(
                [
                    {"task": task, "resource": resource, "value": scores[(task, resource)]}
                    for task, resource in sorted(scores)
                ],
                key=lambda item: (item["task"], item["resource"]),
            ),
            "prohibited": sorted(prohibited),
            "capacity": {resource: capacity.get(resource) for resource in sorted(resource_ids)},
            "demand": {task: demand.get(task, 1) for task in sorted(task_ids)},
            "sense": sense.value,
        }
        return cls(
            problem_id=cls.content_id(identity),
            task_ids=task_ids,
            resource_ids=resource_ids,
            score=dict(scores),
            prohibited=prohibited,
            capacity=capacity,
            demand=demand,
            generation={"method": "explicit"},
            sense=sense,
        )

    @classmethod
    def content_id(cls, identity_payload: dict[str, Any]) -> str:
        return _identity_hash("assignment", identity_payload)
