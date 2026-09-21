"""VariaQ: reproducible optimization experiment comparisons."""

__version__ = "0.7.0"

from variaq import adapter, lower, models
from variaq.problems import (
    AssignmentProblem,
    GraphPartitionProblem,
    MaxCutProblem,
    ProblemInstance,
    SubsetSelectionProblem,
)
from variaq.solvers import (
    ExactSolver,
    HeuristicSolver,
    Solver,
    get_solver,
    solver_names,
    solver_supported_families,
)

__all__ = [
    "__version__",
    "adapter",
    "lower",
    "models",
    "AssignmentProblem",
    "GraphPartitionProblem",
    "MaxCutProblem",
    "ProblemInstance",
    "SubsetSelectionProblem",
    "ExactSolver",
    "HeuristicSolver",
    "Solver",
    "get_solver",
    "solver_names",
    "solver_supported_families",
]
