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

    @abstractmethod
    def solve(self, problem: ProblemInstance, config: SolverConfig) -> SolveResult: ...

    @staticmethod
    def validate_parameters(parameters: dict[str, Any], allowed: set[str]) -> None:
        unknown = set(parameters) - allowed
        if unknown:
            raise ValidationError(f"Unsupported solver parameters: {sorted(unknown)}")


def get_solver(name: str) -> Solver:
    normalized = name.strip().lower()
    if normalized == "exact":
        from variaq.solvers.exact import ExactMaxCutSolver

        return ExactMaxCutSolver()
    if normalized in {"heuristic", "local-search"}:
        from variaq.solvers.heuristic import HeuristicMaxCutSolver

        return HeuristicMaxCutSolver()
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
