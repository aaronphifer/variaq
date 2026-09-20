from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from variaq.errors import ValidationError
from variaq.models import Evaluation, OptimizationSense
from variaq.problems.base import ProblemInstance, _identity_hash


@dataclass(frozen=True, slots=True)
class SubsetSelectionProblem(ProblemInstance):
    """Generic bounded subset selection.

    Domain-neutral formulation:
        - candidate_ids: opaque candidate identifiers
        - score[candidate]: individual contribution (float)
        - cost[candidate]: optional per-candidate cost (default 1.0)
        - budget: optional maximum total cost
        - min_cardinality / max_cardinality: optional bounds on subset size
        - interaction[(a, b)]: optional pairwise interaction term (float)

    Canonical objective:
        sum(score[i] * x[i])
      + sum(interaction[(i, j)] * x[i] * x[j])
      where x[i] = 1 if candidate i is selected.

    Constraints:
        - selected subset cardinality must satisfy bounds if given
        - total selected cost must not exceed budget if given

    Pairwise interactions may represent synergy, redundancy, conflict, or diversity;
    VariaQ does not attach domain meaning to them.
    """

    problem_id: str
    candidate_ids: tuple[str, ...]
    score: dict[str, float]
    cost: dict[str, float]
    budget: float | None
    min_cardinality: int | None
    max_cardinality: int | None
    interaction: dict[frozenset[str], float]
    generation: dict[str, Any]
    problem_type: str = "subset-selection"
    family: str = "subset-selection"
    schema_version: int = 1
    sense: OptimizationSense = OptimizationSense.MAXIMIZE

    def __post_init__(self) -> None:
        if not self.candidate_ids:
            raise ValidationError("Subset selection requires at least one candidate")
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValidationError("Duplicate candidate IDs")
        candidates = set(self.candidate_ids)
        for candidate in self.candidate_ids:
            if candidate not in self.score:
                raise ValidationError(f"Missing score for candidate {candidate!r}")
            if candidate not in self.cost:
                raise ValidationError(f"Missing cost for candidate {candidate!r}")
            if self.cost[candidate] < 0:
                raise ValidationError(f"Cost for candidate {candidate!r} must be non-negative")
        unknown_scores = set(self.score) - candidates
        if unknown_scores:
            raise ValidationError(f"Score entries for unknown candidates: {sorted(unknown_scores)}")
        unknown_costs = set(self.cost) - candidates
        if unknown_costs:
            raise ValidationError(f"Cost entries for unknown candidates: {sorted(unknown_costs)}")
        for pair in self.interaction:
            if not pair <= candidates:
                raise ValidationError(f"Interaction {pair} references unknown candidate")
            if len(pair) != 2:
                raise ValidationError("Interaction terms must be candidate pairs")
        if self.budget is not None and self.budget < 0:
            raise ValidationError("Budget must be non-negative")
        if self.min_cardinality is not None and self.min_cardinality < 0:
            raise ValidationError("min_cardinality must be non-negative")
        if self.max_cardinality is not None and self.max_cardinality < 0:
            raise ValidationError("max_cardinality must be non-negative")
        if (
            self.min_cardinality is not None
            and self.max_cardinality is not None
            and self.min_cardinality > self.max_cardinality
        ):
            raise ValidationError(
                f"min_cardinality {self.min_cardinality} exceeds "
                f"max_cardinality {self.max_cardinality}"
            )
        if self.budget is not None:
            min_cost = sum(self.cost[c] for c in self.candidate_ids)
            if self.budget < min_cost and self.min_cardinality == len(self.candidate_ids):
                raise ValidationError(
                    "Budget is smaller than the total cost of all candidates "
                    "while full selection is required"
                )

    @property
    def variable_count(self) -> int:
        return len(self.candidate_ids)

    def evaluate(self, solution: tuple[int, ...] | list[int]) -> Evaluation:
        violations: list[str] = []
        if len(solution) != len(self.candidate_ids):
            violations.append(
                f"solution length {len(solution)} does not match "
                f"candidate count {len(self.candidate_ids)}"
            )
            return Evaluation(
                objective=None, feasible=False, constraint_violations=tuple(violations)
            )
        invalid = [index for index, bit in enumerate(solution) if bit not in (0, 1)]
        if invalid:
            violations.append(f"non-binary values at indices {invalid}")
            return Evaluation(
                objective=None, feasible=False, constraint_violations=tuple(violations)
            )

        selected = {self.candidate_ids[index] for index, bit in enumerate(solution) if bit}
        cardinality = len(selected)
        total_cost = sum(self.cost[c] for c in selected)
        objective = sum(self.score[c] for c in selected)
        for pair, value in self.interaction.items():
            if pair <= selected:
                objective += value

        if self.min_cardinality is not None and cardinality < self.min_cardinality:
            violations.append(f"cardinality {cardinality} below minimum {self.min_cardinality}")
        if self.max_cardinality is not None and cardinality > self.max_cardinality:
            violations.append(f"cardinality {cardinality} above maximum {self.max_cardinality}")
        if self.budget is not None and total_cost > self.budget:
            violations.append(f"total cost {total_cost} exceeds budget {self.budget}")

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
            "candidate_ids": list(self.candidate_ids),
            "score": {c: self.score[c] for c in self.candidate_ids},
            "cost": {c: self.cost[c] for c in self.candidate_ids},
            "budget": self.budget,
            "min_cardinality": self.min_cardinality,
            "max_cardinality": self.max_cardinality,
            "interaction": [
                {"a": sorted(pair)[0], "b": sorted(pair)[1], "value": value}
                for pair, value in sorted(self.interaction.items(), key=lambda kv: sorted(kv[0]))
            ],
            "generation": self.generation,
        }

    def identity_payload(self) -> dict[str, Any]:
        return {
            "candidate_ids": sorted(self.candidate_ids),
            "score": {c: self.score[c] for c in sorted(self.candidate_ids)},
            "cost": {c: self.cost[c] for c in sorted(self.candidate_ids)},
            "budget": self.budget,
            "min_cardinality": self.min_cardinality,
            "max_cardinality": self.max_cardinality,
            "interaction": [
                {"a": sorted(pair)[0], "b": sorted(pair)[1], "value": value}
                for pair, value in sorted(self.interaction.items(), key=lambda kv: sorted(kv[0]))
            ],
            "sense": self.sense.value,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SubsetSelectionProblem:
        if value.get("schema_version") != 1:
            raise ValidationError(
                f"Unsupported subset-selection schema version: {value.get('schema_version')}"
            )
        try:
            candidate_ids = tuple(str(c) for c in value["candidate_ids"])
            score = {str(k): float(v) for k, v in value["score"].items()}
            cost = {str(k): float(v) for k, v in value["cost"].items()}
            budget = value.get("budget")
            if budget is not None:
                budget = float(budget)
            min_cardinality = value.get("min_cardinality")
            max_cardinality = value.get("max_cardinality")
            if min_cardinality is not None:
                min_cardinality = int(min_cardinality)
            if max_cardinality is not None:
                max_cardinality = int(max_cardinality)
            interaction: dict[frozenset[str], float] = {}
            for entry in value.get("interaction", []):
                pair = frozenset({str(entry["a"]), str(entry["b"])})
                interaction[pair] = float(entry["value"])
            problem = cls(
                problem_id=str(value["problem_id"]),
                candidate_ids=candidate_ids,
                score=score,
                cost=cost,
                budget=budget,
                min_cardinality=min_cardinality,
                max_cardinality=max_cardinality,
                interaction=interaction,
                generation=dict(value.get("generation", {})),
                sense=OptimizationSense(value.get("sense", "maximize")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(f"Invalid subset-selection document: {exc}") from exc
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
        candidate_count: int,
        seed: int,
        budget: float | None = None,
        min_cardinality: int | None = None,
        max_cardinality: int | None = None,
        interaction_probability: float = 0.0,
        sense: OptimizationSense = OptimizationSense.MAXIMIZE,
    ) -> SubsetSelectionProblem:
        if candidate_count < 1:
            raise ValidationError("candidate_count must be positive")
        if not 0.0 <= interaction_probability <= 1.0:
            raise ValidationError("interaction_probability must be between 0 and 1")
        rng = random.Random(seed)
        candidate_ids = tuple(f"candidate-{index}" for index in range(candidate_count))
        score = {candidate: round(rng.uniform(-10.0, 10.0), 4) for candidate in candidate_ids}
        cost = {candidate: round(rng.uniform(1.0, 5.0), 4) for candidate in candidate_ids}
        interaction: dict[frozenset[str], float] = {}
        candidates_list = list(candidate_ids)
        for i in range(candidate_count):
            for j in range(i + 1, candidate_count):
                if rng.random() < interaction_probability:
                    pair = frozenset({candidates_list[i], candidates_list[j]})
                    interaction[pair] = round(rng.uniform(-10.0, 10.0), 4)
        if budget is None:
            budget = sum(cost.values())
        identity = {
            "candidate_ids": sorted(candidate_ids),
            "score": {c: score[c] for c in sorted(candidate_ids)},
            "cost": {c: cost[c] for c in sorted(candidate_ids)},
            "budget": budget,
            "min_cardinality": min_cardinality,
            "max_cardinality": max_cardinality,
            "interaction": [
                {"a": sorted(pair)[0], "b": sorted(pair)[1], "value": value}
                for pair, value in sorted(interaction.items(), key=lambda kv: sorted(kv[0]))
            ],
            "sense": sense.value,
        }
        return cls(
            problem_id=cls.content_id(identity),
            candidate_ids=candidate_ids,
            score=score,
            cost=cost,
            budget=budget,
            min_cardinality=min_cardinality,
            max_cardinality=max_cardinality,
            interaction=interaction,
            generation={
                "method": "random_subset",
                "candidate_count": candidate_count,
                "budget": budget,
                "min_cardinality": min_cardinality,
                "max_cardinality": max_cardinality,
                "interaction_probability": interaction_probability,
                "seed": seed,
            },
            sense=sense,
        )

    @classmethod
    def from_data(
        cls,
        candidate_ids: tuple[str, ...] | list[str],
        score: dict[str, float],
        *,
        cost: dict[str, float] | None = None,
        budget: float | None = None,
        min_cardinality: int | None = None,
        max_cardinality: int | None = None,
        interaction: dict[frozenset[str], float] | None = None,
        sense: OptimizationSense = OptimizationSense.MAXIMIZE,
    ) -> SubsetSelectionProblem:
        candidate_ids = tuple(candidate_ids)
        if cost is None:
            cost = {c: 1.0 for c in candidate_ids}
        identity = {
            "candidate_ids": sorted(candidate_ids),
            "score": {c: score[c] for c in sorted(candidate_ids)},
            "cost": {c: cost[c] for c in sorted(candidate_ids)},
            "budget": budget,
            "min_cardinality": min_cardinality,
            "max_cardinality": max_cardinality,
            "interaction": [
                {"a": sorted(pair)[0], "b": sorted(pair)[1], "value": value}
                for pair, value in sorted((interaction or {}).items(), key=lambda kv: sorted(kv[0]))
            ],
            "sense": sense.value,
        }
        return cls(
            problem_id=cls.content_id(identity),
            candidate_ids=candidate_ids,
            score=dict(score),
            cost=dict(cost),
            budget=budget,
            min_cardinality=min_cardinality,
            max_cardinality=max_cardinality,
            interaction=dict(interaction or {}),
            generation={"method": "explicit"},
            sense=sense,
        )

    @classmethod
    def content_id(cls, identity_payload: dict[str, Any]) -> str:
        return _identity_hash("subset", identity_payload)
