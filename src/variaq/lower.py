"""Backend-neutral binary quadratic lowering for VariaQ problem families.

This module provides an OPTIONAL solver input artifact. The domain problem
remains authoritative; any lowered representation must be decoded, validated,
and evaluated through the original problem before being reported as a result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from variaq.errors import ValidationError
from variaq.models import OptimizationSense
from variaq.problems.assignment import AssignmentProblem
from variaq.problems.base import ProblemInstance
from variaq.problems.graph_partition import GraphPartitionProblem
from variaq.problems.maxcut import MaxCutProblem
from variaq.problems.subset_selection import SubsetSelectionProblem


@dataclass(frozen=True, slots=True)
class BinaryQuadraticModel:
    """Backend-neutral QUBO/Ising-style representation.

    Fields:
        variable_ids: ordered list of binary variable identifiers
        linear: linear coefficients by variable_id
        quadratic: quadratic coefficients keyed by frozenset of two variable_ids
        offset: constant term
        sense: maximize or minimize
        penalty_metadata: structured information about constraint penalties,
            including the source problem family and any penalty coefficients used
        decode: mapping from variable index to semantic role in the source problem
    """

    variable_ids: tuple[str, ...]
    linear: dict[str, float]
    quadratic: dict[frozenset[str], float]
    offset: float
    sense: OptimizationSense
    penalty_metadata: dict[str, Any]
    decode: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "variable_ids": list(self.variable_ids),
            "linear": {k: v for k, v in self.linear.items()},
            "quadratic": [
                {"variables": sorted(pair), "coefficient": value}
                for pair, value in sorted(self.quadratic.items(), key=lambda kv: sorted(kv[0]))
            ],
            "offset": self.offset,
            "sense": self.sense.value,
            "penalty_metadata": self.penalty_metadata,
            "decode": list(self.decode),
        }


def lower_to_binary_quadratic(problem: ProblemInstance) -> BinaryQuadraticModel:
    """Return a backend-neutral binary quadratic representation when supported."""
    if isinstance(problem, MaxCutProblem):
        return _maxcut_lower(problem)
    if isinstance(problem, AssignmentProblem):
        return _assignment_lower(problem)
    if isinstance(problem, SubsetSelectionProblem):
        return _subset_lower(problem)
    if isinstance(problem, GraphPartitionProblem):
        return _graph_partition_lower(problem)
    raise ValidationError(
        f"Binary quadratic lowering is not supported for family {problem.family!r}"
    )


def _maxcut_lower(problem: MaxCutProblem) -> BinaryQuadraticModel:
    variable_ids = tuple(f"x_{i}" for i in range(problem.node_count))
    linear: dict[str, float] = {v: 0.0 for v in variable_ids}
    quadratic: dict[frozenset[str], float] = {}
    offset = sum(edge.weight * 0.5 for edge in problem.edges)
    for edge in problem.edges:
        u = variable_ids[edge.u]
        v = variable_ids[edge.v]
        key = frozenset({u, v})
        quadratic[key] = quadratic.get(key, 0.0) - edge.weight
    decode = tuple(
        {"family": "maxcut", "node_index": i, "node": i} for i in range(problem.node_count)
    )
    return BinaryQuadraticModel(
        variable_ids=variable_ids,
        linear=linear,
        quadratic=quadratic,
        offset=offset,
        sense=problem.sense,
        penalty_metadata={"family": "maxcut", "constraint_penalties": {}},
        decode=decode,
    )


def _assignment_lower(problem: AssignmentProblem) -> BinaryQuadraticModel:
    """One-hot encoding per task. Penalty weight is derived from a configurable
    large constant relative to score magnitudes so that infeasible assignments
    have higher energy than any feasible assignment.
    """
    task_count = len(problem.task_ids)
    variable_ids = tuple(
        f"x_{task}_{resource}" for task in problem.task_ids for resource in problem.resource_ids
    )
    linear: dict[str, float] = {v: 0.0 for v in variable_ids}
    quadratic: dict[frozenset[str], float] = {}
    offset = 0.0

    # Objective terms
    for (task, resource), value in problem.score.items():
        var = f"x_{task}_{resource}"
        linear[var] += value if problem.sense.value == "maximize" else -value

    max_abs_score = max((abs(v) for v in problem.score.values()), default=0.0)
    penalty = max(1.0, max_abs_score * 10.0) + (
        sum((problem.capacity.get(r) or 0) for r in problem.resource_ids) + task_count
    )

    # Each task assigned exactly demand[task] times
    for task in problem.task_ids:
        task_vars = [f"x_{task}_{r}" for r in problem.resource_ids]
        demand = problem.demand.get(task, 1)
        for i, vi in enumerate(task_vars):
            for j, vj in enumerate(task_vars):
                if i < j:
                    key = frozenset({vi, vj})
                    quadratic[key] = quadratic.get(key, 0.0) + penalty
        for vi in task_vars:
            linear[vi] += penalty * (1 - 2 * demand)
        offset += penalty * demand * demand

    # Prohibited pairs receive a large positive penalty
    for task, resource in problem.prohibited:
        var = f"x_{task}_{resource}"
        linear[var] += penalty * 10.0

    # Resource capacities: penalty when load exceeds capacity
    for resource in problem.resource_ids:
        cap = problem.capacity.get(resource)
        if cap is None:
            continue
        resource_vars = [f"x_{t}_{resource}" for t in problem.task_ids]
        for _i, vi in enumerate(resource_vars):
            linear[vi] += penalty * 10.0
        for i, vi in enumerate(resource_vars):
            for j, vj in enumerate(resource_vars):
                if i < j:
                    key = frozenset({vi, vj})
                    quadratic[key] = quadratic.get(key, 0.0) - penalty * 10.0
        offset += penalty * 10.0 * cap * cap

    if problem.sense.value == "minimize":
        offset = -offset

    decode = tuple(
        {"family": "assignment", "task": task, "resource": resource}
        for task in problem.task_ids
        for resource in problem.resource_ids
    )
    return BinaryQuadraticModel(
        variable_ids=variable_ids,
        linear=linear,
        quadratic=quadratic,
        offset=offset,
        sense=OptimizationSense.MINIMIZE,
        penalty_metadata={
            "family": "assignment",
            "constraint_penalties": {"assignment_equality": penalty, "prohibited": penalty * 10.0},
            "derived_from_max_abs_score": max_abs_score,
        },
        decode=decode,
    )


def _subset_lower(problem: SubsetSelectionProblem) -> BinaryQuadraticModel:
    variable_ids = tuple(f"x_{c}" for c in problem.candidate_ids)
    linear: dict[str, float] = {v: 0.0 for v in variable_ids}
    quadratic: dict[frozenset[str], float] = {}

    for candidate, value in problem.score.items():
        var = f"x_{candidate}"
        linear[var] += value if problem.sense.value == "maximize" else -value

    for pair, value in problem.interaction.items():
        a, b = sorted(pair)
        key = frozenset({f"x_{a}", f"x_{b}"})
        quadratic[key] = quadratic.get(key, 0.0) + value

    offset = 0.0
    max_abs = max(
        (abs(v) for v in list(problem.score.values()) + list(problem.interaction.values())),
        default=0.0,
    )
    penalty = max(1.0, max_abs * 10.0)

    # Budget penalty: (sum cost_i x_i - budget)^2
    if problem.budget is not None:
        for candidate in problem.candidate_ids:
            var = f"x_{candidate}"
            linear[var] += (
                penalty
                * problem.cost.get(candidate, 1.0)
                * (problem.cost.get(candidate, 1.0) - 2 * problem.budget)
            )
        for i, ci in enumerate(problem.candidate_ids):
            for j, cj in enumerate(problem.candidate_ids):
                if i < j:
                    key = frozenset({f"x_{ci}", f"x_{cj}"})
                    quadratic[key] = quadratic.get(key, 0.0) + 2 * penalty * problem.cost.get(
                        ci, 1.0
                    ) * problem.cost.get(cj, 1.0)
        offset += penalty * problem.budget * problem.budget

    # Cardinality penalties encoded as squared violations
    if problem.min_cardinality is not None:
        for candidate in problem.candidate_ids:
            linear[f"x_{candidate}"] += penalty * (1 - 2 * problem.min_cardinality)
        for i, ci in enumerate(problem.candidate_ids):
            for j, cj in enumerate(problem.candidate_ids):
                if i < j:
                    key = frozenset({f"x_{ci}", f"x_{cj}"})
                    quadratic[key] = quadratic.get(key, 0.0) + 2 * penalty
        offset += penalty * problem.min_cardinality * problem.min_cardinality
    if problem.max_cardinality is not None:
        for candidate in problem.candidate_ids:
            linear[f"x_{candidate}"] += penalty * (1 - 2 * problem.max_cardinality)
        for i, ci in enumerate(problem.candidate_ids):
            for j, cj in enumerate(problem.candidate_ids):
                if i < j:
                    key = frozenset({f"x_{ci}", f"x_{cj}"})
                    quadratic[key] = quadratic.get(key, 0.0) + 2 * penalty
        offset += penalty * problem.max_cardinality * problem.max_cardinality

    if problem.sense.value == "minimize":
        offset = -offset

    return BinaryQuadraticModel(
        variable_ids=variable_ids,
        linear=linear,
        quadratic=quadratic,
        offset=offset,
        sense=OptimizationSense.MINIMIZE,
        penalty_metadata={
            "family": "subset-selection",
            "constraint_penalties": {
                "budget": penalty if problem.budget is not None else None,
                "min_cardinality": penalty if problem.min_cardinality is not None else None,
                "max_cardinality": penalty if problem.max_cardinality is not None else None,
            },
        },
        decode=tuple({"family": "subset-selection", "candidate": c} for c in problem.candidate_ids),
    )


def _graph_partition_lower(problem: GraphPartitionProblem) -> BinaryQuadraticModel:
    # One-hot encoding per node to partition.
    variable_ids = tuple(
        f"x_{node}_{p}" for node in problem.node_ids for p in range(problem.partition_count)
    )
    linear: dict[str, float] = {v: 0.0 for v in variable_ids}
    quadratic: dict[frozenset[str], float] = {}
    offset = 0.0

    # Cut objective: weight * (x_u_p * (1 - x_v_p)) across partitions and edges
    for u, v, weight in problem.edges:
        for p in range(problem.partition_count):
            up = f"x_{u}_{p}"
            vp = f"x_{v}_{p}"
            linear[up] += weight
            linear[vp] += weight
            key = frozenset({up, vp})
            quadratic[key] = quadratic.get(key, 0.0) - 2 * weight
        offset += weight

    max_weight = max((e[2] for e in problem.edges), default=0.0)
    penalty = max(1.0, max_weight * 10.0)

    # Each node assigned to exactly one partition
    for node in problem.node_ids:
        node_vars = [f"x_{node}_{p}" for p in range(problem.partition_count)]
        for i, vi in enumerate(node_vars):
            for j, vj in enumerate(node_vars):
                if i < j:
                    key = frozenset({vi, vj})
                    quadratic[key] = quadratic.get(key, 0.0) + penalty
        for vi in node_vars:
            linear[vi] += penalty
        offset += penalty

    if problem.sense.value == "maximize":
        # negate all coefficients to convert minimize-cut to maximize
        for k in linear:
            linear[k] = -linear[k]
        for k in quadratic:
            quadratic[k] = -quadratic[k]
        offset = -offset

    decode = tuple(
        {"family": "graph-partition", "node": node, "partition": p}
        for node in problem.node_ids
        for p in range(problem.partition_count)
    )
    return BinaryQuadraticModel(
        variable_ids=variable_ids,
        linear=linear,
        quadratic=quadratic,
        offset=offset,
        sense=problem.sense,
        penalty_metadata={
            "family": "graph-partition",
            "constraint_penalties": {"one_hot_per_node": penalty},
        },
        decode=decode,
    )


def decode_solution(model: BinaryQuadraticModel, state: dict[str, int]) -> tuple[int, ...]:
    """Convert a QUBO state (variable_id -> 0/1) to a VariaQ binary solution.

    The returned tuple follows the original problem's canonical variable ordering.
    """
    if set(state.keys()) != set(model.variable_ids):
        raise ValidationError(
            f"State variables {sorted(state.keys())} do not match model variables"
        )
    return tuple(int(state[var_id]) for var_id in model.variable_ids)


def evaluate_lowered(model: BinaryQuadraticModel, state: dict[str, int]) -> float:
    """Evaluate the lowered quadratic objective for a given state.

    This is a helper for solvers, not an authoritative domain result.
    """
    objective = model.offset
    for var_id, value in state.items():
        if value not in (0, 1):
            raise ValidationError(f"Variable {var_id!r} has non-binary value {value}")
        objective += model.linear.get(var_id, 0.0) * value
    for pair, coeff in model.quadratic.items():
        a, b = pair
        objective += coeff * state[a] * state[b]
    return objective
