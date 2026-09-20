from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from variaq.errors import ValidationError
from variaq.models import SolverConfig, SolveResult
from variaq.problems.base import ProblemInstance


class Solver(ABC):
    """Stable solver interface; implementations return one normalized result."""

    name: str
    version: str
    supported_families: frozenset[str]

    @abstractmethod
    def solve(self, problem: ProblemInstance, config: SolverConfig) -> SolveResult: ...

    @staticmethod
    def validate_parameters(parameters: dict[str, Any], allowed: set[str]) -> None:
        unknown = set(parameters) - allowed
        if unknown:
            raise ValidationError(f"Unsupported solver parameters: {sorted(unknown)}")

    def check_family(self, problem: ProblemInstance) -> None:
        if problem.family not in self.supported_families:
            raise ValidationError(
                f"Solver {self.name!r} does not support problem family {problem.family!r}; "
                f"supported families: {sorted(self.supported_families)}"
            )


def get_solver(name: str) -> Solver:
    normalized = name.strip().lower()
    if normalized == "exact":
        from variaq.solvers.exact import ExactSolver

        return ExactSolver()
    if normalized in {"heuristic", "local-search"}:
        from variaq.solvers.heuristic import HeuristicSolver

        return HeuristicSolver()
    if normalized in {"qaoa", "qiskit-qaoa"}:
        from variaq.solvers.qiskit_qaoa import QiskitQAOASolver

        return QiskitQAOASolver()
    if normalized in {"cudaq-cpu", "cudaq-qaoa-cpu"}:
        from variaq.solvers.cudaq_qaoa import CudaQQAOACpuSolver

        return CudaQQAOACpuSolver()
    if normalized in {"cudaq-gpu", "cudaq-qaoa-gpu"}:
        from variaq.solvers.cudaq_qaoa import CudaQQAOAGpuSolver

        return CudaQQAOAGpuSolver()
    raise ValidationError(f"Unknown solver {name!r}; choose from {', '.join(solver_names())}")


def solver_names() -> tuple[str, ...]:
    return ("exact", "heuristic", "qaoa", "cudaq-cpu", "cudaq-gpu")


def solver_supported_families(solver_name: str) -> frozenset[str]:
    try:
        return get_solver(solver_name).supported_families
    except Exception:
        return frozenset()
