"""Public domain adapter SDK for external VariaQ consumers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from variaq.models import SolveResult
from variaq.problems.base import ProblemInstance


@dataclass(frozen=True, slots=True)
class AdapterResult:
    """Container returned by a domain adapter from_variaq method.

    Holds the translated result plus an opaque, JSON-safe context that can be
    used to map VariaQ IDs back to external project IDs without storing domain
    metadata inside VariaQ's solver model.
    """

    result: Any
    context: dict[str, Any]


class DomainAdapter(ABC):
    """Small public adapter boundary.

    Implementations live in external packages and translate between a domain
    project's objects and VariaQ's generic problem families and results.
    """

    problem_family: str

    @abstractmethod
    def to_variaq(self, source: Any) -> ProblemInstance: ...

    @abstractmethod
    def from_variaq(self, result: SolveResult, context: Any) -> AdapterResult: ...


def adapter_context(mapping: dict[str, Any]) -> dict[str, Any]:
    """Normalize an adapter's private mapping into a JSON-safe context."""
    output: dict[str, Any] = {}
    for key, value in mapping.items():
        if isinstance(value, dict):
            output[str(key)] = adapter_context(value)
        elif isinstance(value, (str, int, float, bool, type(None))):
            output[str(key)] = value
        elif isinstance(value, (list, tuple)):
            output[str(key)] = [str(item) for item in value]
        else:
            output[str(key)] = str(value)
    return output
