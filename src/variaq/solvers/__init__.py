from variaq.solvers.base import Solver, get_solver, solver_names, solver_supported_families
from variaq.solvers.cudaq_qaoa import CudaQQAOACpuSolver, CudaQQAOAGpuSolver
from variaq.solvers.exact import ExactSolver
from variaq.solvers.heuristic import HeuristicSolver
from variaq.solvers.qiskit_qaoa import QiskitQAOASolver

__all__ = [
    "ExactSolver",
    "HeuristicSolver",
    "QiskitQAOASolver",
    "CudaQQAOACpuSolver",
    "CudaQQAOAGpuSolver",
    "Solver",
    "get_solver",
    "solver_names",
    "solver_supported_families",
]

# Backwards-compatible aliases for existing test/consumer imports.
ExactMaxCutSolver = ExactSolver
HeuristicMaxCutSolver = HeuristicSolver
__all__.extend(["ExactMaxCutSolver", "HeuristicMaxCutSolver"])
