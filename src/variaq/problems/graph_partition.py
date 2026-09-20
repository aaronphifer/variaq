from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from variaq.errors import ValidationError
from variaq.models import Evaluation, OptimizationSense
from variaq.problems.base import ProblemInstance, _identity_hash


@dataclass(frozen=True, slots=True)
class GraphPartitionProblem(ProblemInstance):
    """Generic weighted graph partitioning.

    Domain-neutral formulation:
        - node_ids: opaque node identifiers
        - edges: weighted undirected edges among node IDs
        - partition_count k: number of partitions (k >= 2)
        - min_partition_size / max_partition_size: optional per-partition size bounds

    Canonical objective (initial form):
        minimize total weight of edges whose endpoints lie in different partitions.

    Binary encoding: one variable per (node, partition) pair indicating membership.
    """

    problem_id: str
    node_ids: tuple[str, ...]
    edges: tuple[tuple[str, str, float], ...]
    partition_count: int
    min_partition_size: int | None
    max_partition_size: int | None
    generation: dict[str, Any]
    problem_type: str = "graph-partition"
    family: str = "graph-partition"
    schema_version: int = 1
    sense: OptimizationSense = OptimizationSense.MINIMIZE

    def __post_init__(self) -> None:
        if not self.node_ids:
            raise ValidationError("Graph partition requires at least one node")
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValidationError("Duplicate node IDs")
        if self.partition_count < 2:
            raise ValidationError("partition_count must be at least 2")
        nodes = set(self.node_ids)
        seen_edges: set[frozenset[str]] = set()
        for edge in self.edges:
            if len(edge) != 3:
                raise ValidationError("Each edge must be (u, v, weight)")
            u, v, weight = edge
            if u not in nodes or v not in nodes:
                raise ValidationError(f"Edge references unknown node: ({u}, {v})")
            if u == v:
                raise ValidationError("Self-loops are not allowed")
            if weight <= 0:
                raise ValidationError(f"Edge weight must be positive: {weight}")
            key = frozenset({u, v})
            if key in seen_edges:
                raise ValidationError(f"Duplicate edge: ({u}, {v})")
            seen_edges.add(key)
        n = len(self.node_ids)
        if self.min_partition_size is not None:
            if self.min_partition_size < 0:
                raise ValidationError("min_partition_size must be non-negative")
            if self.min_partition_size * self.partition_count > n:
                raise ValidationError(
                    f"min_partition_size {self.min_partition_size} impossible for {n} nodes "
                    f"and {self.partition_count} partitions"
                )
        if self.max_partition_size is not None:
            if self.max_partition_size < 0:
                raise ValidationError("max_partition_size must be non-negative")
            if self.max_partition_size * self.partition_count < n:
                raise ValidationError(
                    f"max_partition_size {self.max_partition_size} too small for {n} nodes "
                    f"and {self.partition_count} partitions"
                )
        if (
            self.min_partition_size is not None
            and self.max_partition_size is not None
            and self.min_partition_size > self.max_partition_size
        ):
            raise ValidationError(
                f"min_partition_size {self.min_partition_size} exceeds "
                f"max_partition_size {self.max_partition_size}"
            )

    @property
    def variable_count(self) -> int:
        return len(self.node_ids) * self.partition_count

    def evaluate(self, solution: tuple[int, ...] | list[int]) -> Evaluation:
        violations: list[str] = []
        expected = self.variable_count
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

        partition_assignments: dict[str, int | None] = {node: None for node in self.node_ids}
        partition_sizes: dict[int, int] = {p: 0 for p in range(self.partition_count)}
        for node_index, node in enumerate(self.node_ids):
            assigned = [
                partition
                for partition in range(self.partition_count)
                if solution[node_index * self.partition_count + partition]
            ]
            if len(assigned) != 1:
                violations.append(
                    f"node {node} assigned to {len(assigned)} partitions, expected exactly 1"
                )
            else:
                partition_assignments[node] = assigned[0]
                partition_sizes[assigned[0]] += 1

        for partition, size in partition_sizes.items():
            if self.min_partition_size is not None and size < self.min_partition_size:
                violations.append(
                    f"partition {partition} size {size} below minimum {self.min_partition_size}"
                )
            if self.max_partition_size is not None and size > self.max_partition_size:
                violations.append(
                    f"partition {partition} size {size} above maximum {self.max_partition_size}"
                )

        feasible = not violations
        objective = 0.0
        if feasible:
            for u, v, weight in self.edges:
                assert partition_assignments[u] is not None
                assert partition_assignments[v] is not None
                if partition_assignments[u] != partition_assignments[v]:
                    objective += weight

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
            "node_ids": list(self.node_ids),
            "edges": [{"u": u, "v": v, "weight": w} for u, v, w in self.edges],
            "partition_count": self.partition_count,
            "min_partition_size": self.min_partition_size,
            "max_partition_size": self.max_partition_size,
            "generation": self.generation,
        }

    def identity_payload(self) -> dict[str, Any]:
        return {
            "node_ids": sorted(self.node_ids),
            "edges": sorted(
                [{"u": u, "v": v, "weight": w} for u, v, w in self.edges],
                key=lambda item: (item["u"], item["v"]),
            ),
            "partition_count": self.partition_count,
            "min_partition_size": self.min_partition_size,
            "max_partition_size": self.max_partition_size,
            "sense": self.sense.value,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> GraphPartitionProblem:
        if value.get("schema_version") != 1:
            raise ValidationError(
                f"Unsupported graph-partition schema version: {value.get('schema_version')}"
            )
        try:
            node_ids = tuple(str(n) for n in value["node_ids"])
            edges = tuple(
                (str(edge["u"]), str(edge["v"]), float(edge["weight"])) for edge in value["edges"]
            )
            problem = cls(
                problem_id=str(value["problem_id"]),
                node_ids=node_ids,
                edges=edges,
                partition_count=int(value["partition_count"]),
                min_partition_size=value.get("min_partition_size"),
                max_partition_size=value.get("max_partition_size"),
                generation=dict(value.get("generation", {})),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(f"Invalid graph-partition document: {exc}") from exc
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
        node_count: int,
        edge_probability: float,
        partition_count: int,
        seed: int,
        min_partition_size: int | None = None,
        max_partition_size: int | None = None,
    ) -> GraphPartitionProblem:
        if node_count < 1:
            raise ValidationError("node_count must be positive")
        if not 0.0 <= edge_probability <= 1.0:
            raise ValidationError("edge_probability must be between 0 and 1")
        if partition_count < 2:
            raise ValidationError("partition_count must be at least 2")
        if partition_count > node_count:
            raise ValidationError("partition_count cannot exceed node_count")
        rng = random.Random(seed)
        node_ids = tuple(f"node-{index}" for index in range(node_count))
        edges: list[tuple[str, str, float]] = []
        for i in range(node_count):
            for j in range(i + 1, node_count):
                if rng.random() < edge_probability:
                    weight = round(rng.uniform(0.5, 5.0), 4)
                    edges.append((node_ids[i], node_ids[j], weight))
        identity = {
            "node_ids": sorted(node_ids),
            "edges": sorted(
                [{"u": u, "v": v, "weight": w} for u, v, w in edges],
                key=lambda item: (item["u"], item["v"]),
            ),
            "partition_count": partition_count,
            "min_partition_size": min_partition_size,
            "max_partition_size": max_partition_size,
            "sense": OptimizationSense.MINIMIZE.value,
        }
        return cls(
            problem_id=cls.content_id(identity),
            node_ids=node_ids,
            edges=tuple(edges),
            partition_count=partition_count,
            min_partition_size=min_partition_size,
            max_partition_size=max_partition_size,
            generation={
                "method": "erdos_renyi_gnp_partition",
                "edge_probability": edge_probability,
                "partition_count": partition_count,
                "seed": seed,
            },
        )

    @classmethod
    def from_edges(
        cls,
        node_ids: tuple[str, ...] | list[str],
        edges: list[tuple[str, str] | tuple[str, str, float]],
        partition_count: int,
        *,
        min_partition_size: int | None = None,
        max_partition_size: int | None = None,
    ) -> GraphPartitionProblem:
        node_ids = tuple(node_ids)
        normalized_edges = tuple(
            (
                str(edge[0]) if str(edge[0]) < str(edge[1]) else str(edge[1]),
                str(edge[1]) if str(edge[0]) < str(edge[1]) else str(edge[0]),
                float(edge[2]) if len(edge) == 3 else 1.0,
            )
            for edge in edges
        )
        identity = {
            "node_ids": sorted(node_ids),
            "edges": sorted(
                [{"u": u, "v": v, "weight": w} for u, v, w in normalized_edges],
                key=lambda item: (item["u"], item["v"]),
            ),
            "partition_count": partition_count,
            "min_partition_size": min_partition_size,
            "max_partition_size": max_partition_size,
            "sense": OptimizationSense.MINIMIZE.value,
        }
        return cls(
            problem_id=cls.content_id(identity),
            node_ids=node_ids,
            edges=normalized_edges,
            partition_count=partition_count,
            min_partition_size=min_partition_size,
            max_partition_size=max_partition_size,
            generation={"method": "explicit"},
        )

    @classmethod
    def content_id(cls, identity_payload: dict[str, Any]) -> str:
        return _identity_hash("gpartition", identity_payload)
