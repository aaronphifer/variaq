from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any

from variaq.errors import ValidationError
from variaq.models import Evaluation, OptimizationSense
from variaq.problems.base import ProblemInstance


@dataclass(frozen=True, order=True, slots=True)
class Edge:
    u: int
    v: int
    weight: float = 1.0

    def to_dict(self) -> dict[str, int | float]:
        return {"u": self.u, "v": self.v, "weight": self.weight}


@dataclass(frozen=True, slots=True)
class MaxCutProblem(ProblemInstance):
    problem_id: str
    node_count: int
    edges: tuple[Edge, ...]
    generation: dict[str, Any]
    problem_type: str = "maxcut"
    family: str = "maxcut"
    schema_version: int = 1
    sense: OptimizationSense = OptimizationSense.MAXIMIZE

    def __post_init__(self) -> None:
        if self.node_count < 1:
            raise ValidationError("MaxCut requires at least one node")
        seen: set[tuple[int, int]] = set()
        for edge in self.edges:
            if edge.u < 0 or edge.v < 0 or edge.u >= self.node_count or edge.v >= self.node_count:
                raise ValidationError(f"Edge ({edge.u}, {edge.v}) references a missing node")
            if edge.u >= edge.v:
                raise ValidationError("Edges must be canonical with u < v and no self-loops")
            if edge.weight <= 0:
                raise ValidationError("MaxCut v0.1 requires positive edge weights")
            if (edge.u, edge.v) in seen:
                raise ValidationError(f"Duplicate edge: ({edge.u}, {edge.v})")
            seen.add((edge.u, edge.v))

    @property
    def variable_count(self) -> int:
        return self.node_count

    def evaluate(self, solution: tuple[int, ...] | list[int]) -> Evaluation:
        violations: list[str] = []
        if len(solution) != self.node_count:
            violations.append(
                f"solution length {len(solution)} does not match node count {self.node_count}"
            )
        invalid = [index for index, bit in enumerate(solution) if bit not in (0, 1)]
        if invalid:
            violations.append(f"non-binary values at indices {invalid}")
        if violations:
            return Evaluation(
                objective=None, feasible=False, constraint_violations=tuple(violations)
            )
        objective = sum(edge.weight for edge in self.edges if solution[edge.u] != solution[edge.v])
        return Evaluation(objective=float(objective), feasible=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "problem_id": self.problem_id,
            "problem_type": self.problem_type,
            "family": self.family,
            "sense": self.sense.value,
            "node_count": self.node_count,
            "edges": [edge.to_dict() for edge in self.edges],
            "generation": self.generation,
        }

    def identity_payload(self) -> dict[str, Any]:
        return {
            "node_count": self.node_count,
            "edges": [edge.to_dict() for edge in sorted(self.edges)],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MaxCutProblem:
        if value.get("schema_version") != 1:
            raise ValidationError(
                f"Unsupported MaxCut schema version: {value.get('schema_version')}"
            )
        if value.get("sense") != OptimizationSense.MAXIMIZE.value:
            raise ValidationError("MaxCut v0.1 must use maximize sense")
        try:
            edges = tuple(
                Edge(u=int(edge["u"]), v=int(edge["v"]), weight=float(edge["weight"]))
                for edge in value["edges"]
            )
            problem = cls(
                problem_id=str(value["problem_id"]),
                node_count=int(value["node_count"]),
                edges=edges,
                generation=dict(value.get("generation", {})),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(f"Invalid MaxCut document: {exc}") from exc
        expected_id = cls.content_id(problem.node_count, problem.edges)
        if problem.problem_id != expected_id:
            raise ValidationError(
                "Problem ID does not match content: "
                f"expected {expected_id}, got {problem.problem_id}"
            )
        return problem

    @classmethod
    def generate(cls, node_count: int, edge_probability: float, seed: int) -> MaxCutProblem:
        if node_count < 1:
            raise ValidationError("--nodes must be at least 1")
        if not 0.0 <= edge_probability <= 1.0:
            raise ValidationError("--edge-probability must be between 0 and 1")
        rng = random.Random(seed)
        edges = tuple(
            Edge(u, v)
            for u in range(node_count)
            for v in range(u + 1, node_count)
            if rng.random() < edge_probability
        )
        return cls(
            problem_id=cls.content_id(node_count, edges),
            node_count=node_count,
            edges=edges,
            generation={
                "method": "erdos_renyi_gnp",
                "edge_probability": edge_probability,
                "seed": seed,
            },
        )

    @classmethod
    def from_edges(
        cls, node_count: int, edges: list[tuple[int, int] | tuple[int, int, float]]
    ) -> MaxCutProblem:
        normalized = tuple(
            sorted(
                Edge(
                    min(int(edge[0]), int(edge[1])),
                    max(int(edge[0]), int(edge[1])),
                    float(edge[2]) if len(edge) == 3 else 1.0,
                )
                for edge in edges
            )
        )
        return cls(
            problem_id=cls.content_id(node_count, normalized),
            node_count=node_count,
            edges=normalized,
            generation={"method": "explicit"},
        )

    @staticmethod
    def content_id(node_count: int, edges: tuple[Edge, ...]) -> str:
        identity_payload = {
            "node_count": node_count,
            "edges": [edge.to_dict() for edge in sorted(edges)],
        }
        digest = hashlib.sha256(
            json.dumps(identity_payload, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()[:16]
        return f"maxcut-{digest}"
