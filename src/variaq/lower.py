"""Backend-neutral binary quadratic lowering for VariaQ problem families.

This module provides an OPTIONAL solver input artifact. The domain problem
remains authoritative; any lowered representation must be decoded, validated,
and evaluated through the original problem before being reported as a result.

BQM convention
--------------

The :class:`variaq.bqm.BinaryQuadraticModel` stores a sense-aware surrogate
objective. Its energy is the value that should be optimized in the direction of
``problem.sense``:

    maximize  ->  maximize BQM energy
    minimize  ->  minimize BQM energy

For an unconstrained problem the BQM energy equals the source objective. For
constrained problems, penalty terms are added with a sign that makes infeasible
assignments worse than any feasible assignment. For a maximization problem this
means penalties are subtracted (so they reduce energy when violated); for a
minimization problem penalties are added (so they increase energy when
violated).

This convention preserves VariaQ's established MaxCut QAOA numeric behavior:
the QAOA expectation for a MaxCut instance is the expected cut weight.

Penalty design
--------------

Equality constraints (one-hot per node, per-task assignment demand) are encoded
as squared penalties ``P * (sum x_i - target)^2``. The penalty magnitude ``P``
is chosen so that the maximum objective improvement obtainable by violating the
constraint is smaller than the penalty paid for that violation. This guarantees
that the BQM optimum is a feasible state.

Inequality constraints (budget, cardinality, capacity, partition balance) are
not supported on the QUBO/QAOA path in VariaQ 0.5.0. Pure QUBO encodings of
inequality constraints require slack variables or other auxiliary machinery
that has not yet been verified for this release. Such instances must be solved
with classical solvers in 0.5.0.
"""

from __future__ import annotations

from variaq.bqm import BinaryQuadraticModel, canonicalize_pair
from variaq.errors import ValidationError
from variaq.models import OptimizationSense
from variaq.problems.assignment import AssignmentProblem
from variaq.problems.base import ProblemInstance
from variaq.problems.graph_partition import GraphPartitionProblem
from variaq.problems.maxcut import MaxCutProblem
from variaq.problems.subset_selection import SubsetSelectionProblem


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
    # BQM energy = cut weight.  For edge (u,v,w): cut weight includes
    # w * (x_u + x_v - 2 x_u x_v).  Therefore the energy landscape matches the
    # source objective exactly and the QAOA expectation equals the expected cut.
    node_count = problem.node_count
    variable_ids = tuple(f"x_{i}" for i in range(node_count))
    linear: dict[str, float] = {v: 0.0 for v in variable_ids}
    quadratic: dict[tuple[str, str], float] = {}
    for edge in problem.edges:
        u = variable_ids[edge.u]
        v = variable_ids[edge.v]
        linear[u] += edge.weight
        linear[v] += edge.weight
        pair = canonicalize_pair(u, v)
        quadratic[pair] = quadratic.get(pair, 0.0) - 2.0 * edge.weight
    decode = tuple({"family": "maxcut", "node_index": i, "node": i} for i in range(node_count))
    return BinaryQuadraticModel(
        variable_ids=variable_ids,
        linear=linear,
        quadratic=quadratic,
        offset=0.0,
        sense=problem.sense,
        source_family="maxcut",
        source_problem_id=problem.problem_id,
        penalty_metadata={"family": "maxcut", "constraint_penalties": {}},
        decode=decode,
    )


def _penalty_sign(sense: OptimizationSense) -> float:
    """Return +1 for minimize (penalties increase energy) and -1 for maximize."""
    return 1.0 if sense.value == "minimize" else -1.0


def _add_squared_constraint(
    linear: dict[str, float],
    quadratic: dict[tuple[str, str], float],
    offset: float,
    sign: float,
    penalty: float,
    variables: list[str],
    coefficients: list[float],
    target: float,
) -> float:
    """Add sign * penalty * (sum coeff_i * x_i - target)^2 to the BQM.

    Returns the updated offset.
    """
    n = len(variables)
    for i in range(n):
        a_i = coefficients[i]
        linear[variables[i]] += sign * penalty * (a_i * a_i - 2.0 * target * a_i)
    for i in range(n):
        for j in range(i + 1, n):
            pair = canonicalize_pair(variables[i], variables[j])
            quadratic[pair] = (
                quadratic.get(pair, 0.0) + sign * penalty * 2.0 * coefficients[i] * coefficients[j]
            )
    return offset + sign * penalty * target * target


def _assignment_lower(problem: AssignmentProblem) -> BinaryQuadraticModel:
    """One-hot encoding per task. Penalty weight is derived from a bound on the
    maximum objective improvement obtainable by violating the per-task demand
    equality. This guarantees that every BQM optimum is a feasible assignment.
    """
    task_count = len(problem.task_ids)
    variable_ids = tuple(
        f"x_{task}_{resource}" for task in problem.task_ids for resource in problem.resource_ids
    )
    linear: dict[str, float] = {v: 0.0 for v in variable_ids}
    quadratic: dict[tuple[str, str], float] = {}
    offset = 0.0

    # Objective terms are always added as-is so BQM energy equals source objective.
    for (task, resource), value in problem.score.items():
        var = f"x_{task}_{resource}"
        linear[var] += value

    if any(cap is not None for cap in problem.capacity.values()):
        raise ValidationError(
            "Assignment capacity constraints are not supported on the QUBO/QAOA path "
            "in VariaQ 0.5.0. Remove capacity constraints or use a classical solver."
        )

    max_abs_score = max((abs(v) for v in problem.score.values()), default=0.0)
    # Bound: violating one task's demand by ±1 can change the objective by at most
    # max_abs_score (one extra/missing assignment). Across all tasks the total
    # benefit of any violation pattern is bounded by task_count * max_abs_score.
    # We choose P larger than that bound. A 2x margin is included in the formula.
    penalty = max(1.0, 2.0 * task_count * max_abs_score + 1.0)
    penalty_sign = _penalty_sign(problem.sense)

    # Each task assigned exactly demand[task] times.
    for task in problem.task_ids:
        task_vars = [f"x_{task}_{r}" for r in problem.resource_ids]
        demand = problem.demand.get(task, 1)
        offset = _add_squared_constraint(
            linear,
            quadratic,
            offset,
            penalty_sign,
            penalty,
            task_vars,
            [1.0] * len(task_vars),
            float(demand),
        )

    # Prohibited pairs receive a large linear penalty so the assignment is never
    # preferred over any feasible alternative. The penalty is larger than the
    # maximum possible score improvement from replacing a prohibited assignment
    # with the best allowed alternative (bounded by max_abs_score).
    prohibited_penalty = 2.0 * max_abs_score + penalty
    for task, resource in problem.prohibited:
        var = f"x_{task}_{resource}"
        linear[var] += penalty_sign * prohibited_penalty

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
        sense=problem.sense,
        source_family="assignment",
        source_problem_id=problem.problem_id,
        penalty_metadata={
            "family": "assignment",
            "constraint_penalties": {
                "assignment_equality": penalty,
                "prohibited": prohibited_penalty,
                "capacity": None,
            },
            "derived_from_max_abs_score": max_abs_score,
            "penalty_bound_reason": (
                "P > task_count * max_abs_score ensures violating a demand "
                "equality cannot improve the BQM optimum."
            ),
        },
        decode=decode,
    )


def _subset_lower(problem: SubsetSelectionProblem) -> BinaryQuadraticModel:
    """Unconstrained subset-selection lowering.

    VariaQ 0.5.0 does not support budget or cardinality constraints on the
    QUBO/QAOA path because correct inequality penalties require slack variables
    that have not been verified for this release. Equality constraints on a
    subset (e.g., fixed cardinality) are also rejected here; they may be added
    in a future release once a proven slack encoding is available.
    """
    if problem.budget is not None:
        raise ValidationError(
            "Subset Selection budget constraints are not supported on the QUBO/QAOA path "
            "in VariaQ 0.5.0. Remove the budget or use a classical solver."
        )
    if problem.min_cardinality is not None or problem.max_cardinality is not None:
        raise ValidationError(
            "Subset Selection cardinality constraints are not supported on the QUBO/QAOA path "
            "in VariaQ 0.5.0. Remove the cardinality bounds or use a classical solver."
        )

    variable_ids = tuple(f"x_{c}" for c in problem.candidate_ids)
    linear: dict[str, float] = {v: 0.0 for v in variable_ids}
    quadratic: dict[tuple[str, str], float] = {}

    # Objective terms are always added as-is.
    for candidate, value in problem.score.items():
        var = f"x_{candidate}"
        linear[var] += value

    for pair, value in problem.interaction.items():
        a, b = sorted(pair)
        key = canonicalize_pair(f"x_{a}", f"x_{b}")
        quadratic[key] = quadratic.get(key, 0.0) + value

    decode = tuple({"family": "subset-selection", "candidate": c} for c in problem.candidate_ids)
    return BinaryQuadraticModel(
        variable_ids=variable_ids,
        linear=linear,
        quadratic=quadratic,
        offset=0.0,
        sense=problem.sense,
        source_family="subset-selection",
        source_problem_id=problem.problem_id,
        penalty_metadata={
            "family": "subset-selection",
            "constraint_penalties": {
                "budget": None,
                "min_cardinality": None,
                "max_cardinality": None,
            },
            "note": "Unconstrained lowering: BQM energy equals source objective for every state.",
        },
        decode=decode,
    )


def _graph_partition_lower(problem: GraphPartitionProblem) -> BinaryQuadraticModel:
    """One-hot encoding per node.

    VariaQ 0.5.0 supports only the one-hot-per-node constraint on the QUBO/QAOA
    path. Optional balance constraints are inequalities and are not supported in
    this release.
    """
    if problem.min_partition_size is not None or problem.max_partition_size is not None:
        raise ValidationError(
            "Graph Partition balance constraints are not supported on the QUBO/QAOA path "
            "in VariaQ 0.5.0. Remove the balance bounds or use a classical solver."
        )

    variable_ids = tuple(
        f"x_{node}_{p}" for node in problem.node_ids for p in range(problem.partition_count)
    )
    linear: dict[str, float] = {v: 0.0 for v in variable_ids}
    quadratic: dict[tuple[str, str], float] = {}
    offset = 0.0

    # Cut objective: weight * (x_u_p * (1 - x_v_p)) across partitions and edges.
    # BQM energy equals source objective (minimize cut).
    for u, v, weight in problem.edges:
        for p in range(problem.partition_count):
            up = f"x_{u}_{p}"
            vp = f"x_{v}_{p}"
            linear[up] += weight
            linear[vp] += weight
            pair = canonicalize_pair(up, vp)
            quadratic[pair] = quadratic.get(pair, 0.0) - 2 * weight
        offset += weight

    # Bound: if a node is assigned to more than one partition, the extra
    # assignments can cut at most all edges incident to that node. Therefore the
    # maximum objective improvement obtainable by violating node v's one-hot
    # constraint is the sum of incident edge weights at v. We use a per-node
    # penalty larger than that bound.
    incident_sum: dict[str, float] = {node: 0.0 for node in problem.node_ids}
    for u, v, weight in problem.edges:
        incident_sum[u] += weight
        incident_sum[v] += weight
    max_incident = max(incident_sum.values(), default=0.0)
    # A uniform penalty that exceeds the largest incident sum works for every
    # node. Add a small margin to absorb floating-point rounding.
    penalty = max(1.0, 2.0 * max_incident + 0.5)
    penalty_sign = _penalty_sign(problem.sense)

    # Each node assigned to exactly one partition.
    for node in problem.node_ids:
        node_vars = [f"x_{node}_{p}" for p in range(problem.partition_count)]
        offset = _add_squared_constraint(
            linear, quadratic, offset, penalty_sign, penalty, node_vars, [1.0] * len(node_vars), 1.0
        )

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
        source_family="graph-partition",
        source_problem_id=problem.problem_id,
        penalty_metadata={
            "family": "graph-partition",
            "constraint_penalties": {
                "one_hot_per_node": penalty,
                "balance": None,
            },
            "derived_from_max_incident_weight": max_incident,
            "penalty_bound_reason": (
                "P > 2 * max_incident_weight ensures assigning a node to extra "
                "partitions cannot improve the BQM optimum."
            ),
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
    return model.energy(state)
