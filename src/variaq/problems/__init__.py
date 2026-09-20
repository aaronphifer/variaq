from variaq.problems.assignment import AssignmentProblem
from variaq.problems.base import ProblemInstance, problem_from_dict
from variaq.problems.graph_partition import GraphPartitionProblem
from variaq.problems.maxcut import MaxCutProblem
from variaq.problems.subset_selection import SubsetSelectionProblem

__all__ = [
    "MaxCutProblem",
    "AssignmentProblem",
    "SubsetSelectionProblem",
    "GraphPartitionProblem",
    "ProblemInstance",
    "problem_from_dict",
]
