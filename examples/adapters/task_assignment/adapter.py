from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import variaq
from variaq.problems.assignment import AssignmentProblem


@dataclass
class WorkItem:
    id: str
    required_skill: str


@dataclass
class Worker:
    id: str
    skills: set[str]


@dataclass
class WorkAssignment:
    work_item_id: str
    worker_id: str


class TaskWorkerAdapter(variaq.adapter.DomainAdapter):
    """Neutral example: assign work items to workers by skill match.

    This adapter is intentionally not project-specific. It shows how an
    external domain can map into the generic AssignmentProblem family and back.
    """

    problem_family = "assignment"

    def to_variaq(self, source: tuple[list[WorkItem], list[Worker]]) -> AssignmentProblem:
        items, workers = source
        score: dict[tuple[str, str], float] = {}
        prohibited: set[tuple[str, str]] = set()
        for item in items:
            for worker in workers:
                if item.required_skill in worker.skills:
                    score[(item.id, worker.id)] = 1.0
                else:
                    prohibited.add((item.id, worker.id))
        return AssignmentProblem.from_score_matrix(
            task_ids=[item.id for item in items],
            resource_ids=[worker.id for worker in workers],
            scores=score,
            prohibited=prohibited,
        )

    def from_variaq(
        self, result: variaq.models.SolveResult, context: dict[str, Any]
    ) -> variaq.adapter.AdapterResult:
        if result.solution is None or result.problem_type != "assignment":
            return variaq.adapter.AdapterResult(
                result=[], context={"error": "no assignment solution available"}
            )
        task_ids = context["task_ids"]
        resource_ids = context["resource_ids"]
        resource_count = len(resource_ids)
        assignments: list[WorkAssignment] = []
        for task_index, task in enumerate(task_ids):
            for resource_index, resource in enumerate(resource_ids):
                if result.solution[task_index * resource_count + resource_index]:
                    assignments.append(WorkAssignment(task, resource))
        return variaq.adapter.AdapterResult(
            result=assignments,
            context=variaq.adapter.adapter_context(
                {"task_ids": task_ids, "resource_ids": resource_ids}
            ),
        )


if __name__ == "__main__":
    items = [
        WorkItem("item-a", "network"),
        WorkItem("item-b", "database"),
    ]
    workers = [
        Worker("worker-1", {"network", "security"}),
        Worker("worker-2", {"database", "ui"}),
    ]
    adapter = TaskWorkerAdapter()
    problem = adapter.to_variaq((items, workers))
    print("Problem family:", problem.family)
    print("Problem ID:", problem.problem_id)
    from variaq.models import SolverConfig
    from variaq.solvers.exact import ExactSolver

    result = ExactSolver().solve(problem, SolverConfig(seed=1))
    translated = adapter.from_variaq(
        result,
        {
            "task_ids": list(problem.task_ids),
            "resource_ids": list(problem.resource_ids),
        },
    )
    print("Assignments:", [(a.work_item_id, a.worker_id) for a in translated.result])
    print("Objective:", result.objective)
