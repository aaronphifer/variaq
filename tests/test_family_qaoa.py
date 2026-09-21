"""Tests verifying generic QAOA behavior on each supported family."""

from __future__ import annotations

import unittest

from variaq.errors import ValidationError
from variaq.models import OptimizationSense, SolverConfig
from variaq.problems.assignment import AssignmentProblem
from variaq.problems.graph_partition import GraphPartitionProblem
from variaq.problems.maxcut import MaxCutProblem
from variaq.problems.subset_selection import SubsetSelectionProblem
from variaq.solvers.exact import ExactSolver
from variaq.solvers.heuristic import HeuristicSolver

try:
    import qiskit  # noqa: F401

    from variaq.solvers.qiskit_qaoa import QiskitQAOASolver

    _QISKIT_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    _QISKIT_AVAILABLE = False

try:
    import cudaq  # noqa: F401

    from variaq.solvers.cudaq_qaoa import CudaQQAOACpuSolver

    _CUDA_CPU_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    _CUDA_CPU_AVAILABLE = False


class FamilyQAOATests(unittest.TestCase):
    """End-to-end checks that generic QAOA solvers solve small family instances."""

    def _solve(self, solver, problem, **params) -> tuple[float | None, bool]:
        config = SolverConfig(
            seed=1, parameters={"p": 1, "optimizer_trials": 8, "shots": 64, **params}
        )
        result = solver.solve(problem, config)
        return result.objective, result.feasible

    @unittest.skipUnless(_QISKIT_AVAILABLE, "qiskit optional dependency not available")
    def test_qiskit_maxcut_small_known(self) -> None:
        problem = MaxCutProblem.from_edges(3, [(0, 1, 1.0), (1, 2, 1.0)])
        objective, feasible = self._solve(QiskitQAOASolver(), problem)
        self.assertTrue(feasible)
        self.assertEqual(objective, 2.0)

    @unittest.skipUnless(_QISKIT_AVAILABLE, "qiskit optional dependency not available")
    def test_qiskit_assignment_small(self) -> None:
        problem = AssignmentProblem.from_score_matrix(
            ["t1", "t2"],
            ["r1", "r2"],
            {("t1", "r1"): 5.0, ("t1", "r2"): 1.0, ("t2", "r1"): 2.0, ("t2", "r2"): 4.0},
        )
        objective, feasible = self._solve(QiskitQAOASolver(), problem)
        self.assertTrue(feasible)
        exact = ExactSolver().solve(problem, SolverConfig(seed=1))
        self.assertIsNotNone(exact.objective)
        self.assertEqual(objective, exact.objective)

    @unittest.skipUnless(_QISKIT_AVAILABLE, "qiskit optional dependency not available")
    def test_qiskit_subset_selection_small(self) -> None:
        # Unconstrained subset selection is supported on the QAOA path.
        problem = SubsetSelectionProblem.from_data(
            ["a", "b", "c"],
            {"a": 1.0, "b": 2.0, "c": 3.0},
        )
        objective, feasible = self._solve(QiskitQAOASolver(), problem)
        self.assertTrue(feasible)
        exact = ExactSolver().solve(problem, SolverConfig(seed=1))
        self.assertEqual(objective, exact.objective)

    @unittest.skipUnless(_QISKIT_AVAILABLE, "qiskit optional dependency not available")
    def test_qiskit_graph_partition_not_supported(self) -> None:
        problem = GraphPartitionProblem.from_edges(
            ["a", "b", "c", "d"],
            [
                ("a", "b", 1.0),
                ("b", "c", 1.0),
                ("c", "d", 1.0),
                ("d", "a", 1.0),
            ],
            2,
        )
        solver = QiskitQAOASolver()
        config = SolverConfig(seed=1, parameters={"p": 1, "optimizer_trials": 8, "shots": 64})
        with self.assertRaises(ValidationError):
            solver.solve(problem, config)

    @unittest.skipUnless(_QISKIT_AVAILABLE, "qiskit optional dependency not available")
    def test_qiskit_subset_selection_budget_rejected(self) -> None:
        problem = SubsetSelectionProblem.from_data(
            ["a", "b", "c"],
            {"a": 1.0, "b": 2.0, "c": 3.0},
            budget=3.0,
            cost={"a": 2.0, "b": 2.0, "c": 2.0},
        )
        solver = QiskitQAOASolver()
        config = SolverConfig(seed=1, parameters={"p": 1, "optimizer_trials": 8, "shots": 64})
        with self.assertRaises(ValidationError):
            solver.solve(problem, config)

    @unittest.skipUnless(_CUDA_CPU_AVAILABLE, "CUDA-Q CPU simulator not available")
    def test_cudaq_cpu_assignment_small(self) -> None:
        problem = AssignmentProblem.from_score_matrix(
            ["t1", "t2"],
            ["r1", "r2"],
            {("t1", "r1"): 5.0, ("t1", "r2"): 1.0, ("t2", "r1"): 2.0, ("t2", "r2"): 4.0},
        )
        objective, feasible = self._solve(
            CudaQQAOACpuSolver(), problem, p=1, optimizer_trials=8, shots=64
        )
        self.assertTrue(feasible)
        exact = ExactSolver().solve(problem, SolverConfig(seed=1))
        self.assertEqual(objective, exact.objective)


class FamilyBaselineTests(unittest.TestCase):
    """Confirm exact and heuristic baselines remain available for all families."""

    def test_exact_and_heuristic_baselines_for_all_families(self) -> None:
        families = {
            "maxcut": MaxCutProblem.from_edges(3, [(0, 1, 1.0), (1, 2, 1.0)]),
            "assignment": AssignmentProblem.from_score_matrix(
                ["t1", "t2"],
                ["r1", "r2"],
                {("t1", "r1"): 5.0, ("t1", "r2"): 1.0, ("t2", "r1"): 2.0, ("t2", "r2"): 4.0},
            ),
            "subset-selection": SubsetSelectionProblem.from_data(
                ["a", "b"],
                {"a": 2.0, "b": 3.0},
                sense=OptimizationSense.MINIMIZE,
            ),
            "graph-partition": GraphPartitionProblem.from_edges(
                ["a", "b", "c", "d"],
                [("a", "b", 1.0), ("b", "c", 1.0), ("c", "d", 1.0), ("d", "a", 1.0)],
                2,
            ),
        }
        for label, problem in families.items():
            with self.subTest(family=label):
                exact = ExactSolver().solve(problem, SolverConfig(seed=1))
                self.assertTrue(exact.feasible)
                self.assertIsNotNone(exact.objective)
                heuristic = HeuristicSolver().solve(problem, SolverConfig(seed=1))
                self.assertTrue(heuristic.feasible)
                self.assertIsNotNone(heuristic.objective)


if __name__ == "__main__":
    unittest.main()
