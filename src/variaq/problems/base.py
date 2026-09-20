from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from variaq.errors import ValidationError
from variaq.models import Evaluation, OptimizationSense


class ProblemInstance(ABC):
    """Vendor-neutral problem contract consumed by every solver."""

    problem_id: str
    problem_type: str
    family: str
    schema_version: int
    sense: OptimizationSense

    @property
    @abstractmethod
    def variable_count(self) -> int: ...

    @abstractmethod
    def evaluate(self, solution: tuple[int, ...] | list[int]) -> Evaluation: ...

    @abstractmethod
    def to_dict(self) -> dict[str, Any]: ...

    @abstractmethod
    def identity_payload(self) -> dict[str, Any]:
        """Return only mathematical content used to identify the instance."""
        ...


def _identity_hash(prefix: str, payload: dict[str, Any]) -> str:
    """Stable short hash used for deterministic problem IDs."""
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    digest = hashlib.sha256(canonical).hexdigest()[:16]
    return f"{prefix}-{digest}"


def problem_from_dict(value: dict[str, Any]) -> ProblemInstance:
    problem_type = value.get("problem_type")
    if problem_type == "maxcut":
        from variaq.problems.maxcut import MaxCutProblem

        return MaxCutProblem.from_dict(value)
    if problem_type == "assignment":
        from variaq.problems.assignment import AssignmentProblem

        return AssignmentProblem.from_dict(value)
    if problem_type == "subset-selection":
        from variaq.problems.subset_selection import SubsetSelectionProblem

        return SubsetSelectionProblem.from_dict(value)
    if problem_type == "graph-partition":
        from variaq.problems.graph_partition import GraphPartitionProblem

        return GraphPartitionProblem.from_dict(value)
    raise ValidationError(f"Unsupported problem type: {problem_type!r}")


def save_problem(problem: ProblemInstance, path: Path) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing problem: {path}")
    path.write_text(
        json.dumps(problem.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_problem(path: Path) -> ProblemInstance:
    import json

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Could not load problem from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError("Problem document must be a JSON object")
    return problem_from_dict(value)
