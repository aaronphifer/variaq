from __future__ import annotations

from pathlib import Path

from variaq import __version__
from variaq.errors import ValidationError
from variaq.problems.assignment import AssignmentProblem
from variaq.problems.subset_selection import SubsetSelectionProblem

_ADAPTERS = {
    "assignment": AssignmentProblem,
    "subset-selection": SubsetSelectionProblem,
}
_ADAPTER_MODULES = {
    "assignment": "assignment",
    "subset-selection": "subset_selection",
}


def init_adapter(name: str, family: str, target: Path) -> list[Path]:
    """Scaffold a minimal external domain adapter package.

    Generates a tiny template with imports, to_variaq/from_variaq stubs, one
    test, and a README. The generated code is not automatically installed or
    registered.
    """
    if family not in _ADAPTERS:
        raise ValidationError(
            f"Unsupported adapter family {family!r}; choose from {sorted(_ADAPTERS)}"
        )
    target.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    adapter_py = target / "adapter.py"
    adapter_py.write_text(
        f'''"""Domain adapter for {{name}} using VariaQ's {{family}} family.

This package is a small external adapter. It is not part of VariaQ core and
contains no domain-specific project names by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from variaq.adapter import DomainAdapter, AdapterResult, adapter_context
from variaq.models import SolveResult
from variaq.problems.{_ADAPTER_MODULES[family]} import {_ADAPTERS[family].__name__}


@dataclass
class SourceObject:
    """Replace this with your domain type."""

    id: str


class {name.title().replace("-", "_")}Adapter(DomainAdapter):
    """Translate between your domain objects and VariaQ's {{family}} problem."""

    problem_family = "{family}"

    def to_variaq(self, source: Any) -> {_ADAPTERS[family].__name__}:
        # Implement: map source domain objects to VariaQ generic problem.
        raise NotImplementedError("to_variaq must be implemented")

    def from_variaq(self, result: SolveResult, context: Any) -> AdapterResult:
        # Implement: map VariaQ result back to your domain result.
        return AdapterResult(result=[], context=adapter_context(context))
''',
        encoding="utf-8",
    )
    paths.append(adapter_py)

    test_py = target / "test_adapter.py"
    test_py.write_text(
        f'''"""Tests for the {name} domain adapter."""

from pathlib import Path

from variaq.models import SolverConfig
from variaq.solvers.exact import ExactSolver

from .adapter import SourceObject, {name.title().replace("-", "_")}Adapter


def test_adapter_round_trip():
    # This test is a stub; replace with a real domain object and assertion.
    adapter = {name.title().replace("-", "_")}Adapter()
    # problem = adapter.to_variaq(...)
    # result = ExactSolver().solve(problem, SolverConfig(seed=1))
    # assert result.status == "success"
''',
        encoding="utf-8",
    )
    paths.append(test_py)

    readme = target / "README.md"
    readme.write_text(
        f"""# {{name}} domain adapter

This adapter translates between an external project and VariaQ's generic
`{family}` problem family.

## Generated structure

- `adapter.py`: `to_variaq()` and `from_variaq()` stubs.
- `test_adapter.py`: one tiny round-trip test stub.

## Compatibility

Generated for VariaQ {__version__}. The public adapter surface is intentionally
small, but VariaQ is pre-1.0 and APIs may evolve.
""",
        encoding="utf-8",
    )
    paths.append(readme)
    return paths
