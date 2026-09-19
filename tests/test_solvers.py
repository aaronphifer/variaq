import sys
import unittest
from unittest import mock

from variaq.errors import MissingOptionalDependency, SolverLimitError
from variaq.models import SolverConfig, SolveStatus
from variaq.problems.maxcut import MaxCutProblem
from variaq.solvers.exact import ExactMaxCutSolver
from variaq.solvers.heuristic import HeuristicMaxCutSolver
from variaq.solvers.qiskit_qaoa import QiskitQAOASolver


class ClassicalSolverTests(unittest.TestCase):
    def test_exact_known_optima(self) -> None:
        triangle = MaxCutProblem.from_edges(3, [(0, 1), (1, 2), (0, 2)])
        complete_four = MaxCutProblem.from_edges(
            4, [(u, v) for u in range(4) for v in range(u + 1, 4)]
        )
        solver = ExactMaxCutSolver()
        self.assertEqual(solver.solve(triangle, SolverConfig()).objective, 2.0)
        self.assertEqual(solver.solve(complete_four, SolverConfig()).objective, 4.0)

    def test_exact_guard_prevents_accidental_large_run(self) -> None:
        problem = MaxCutProblem.generate(6, 0.5, 1)
        with self.assertRaises(SolverLimitError):
            ExactMaxCutSolver().solve(problem, SolverConfig(parameters={"max_variables": 5}))

    def test_heuristic_seed_is_repeatable(self) -> None:
        problem = MaxCutProblem.generate(10, 0.4, 42)
        config = SolverConfig(seed=91, parameters={"restarts": 8})
        first = HeuristicMaxCutSolver().solve(problem, config)
        second = HeuristicMaxCutSolver().solve(problem, config)
        self.assertEqual(first.status, SolveStatus.SUCCESS)
        self.assertEqual(first.solution, second.solution)
        self.assertEqual(first.objective, second.objective)


class QiskitSolverTests(unittest.TestCase):
    def test_qiskit_path_is_local_when_installed(self) -> None:
        try:
            import qiskit  # noqa: F401
        except ImportError:
            self.skipTest("optional Qiskit dependency is not installed")
        problem = MaxCutProblem.from_edges(4, [(0, 1), (1, 2), (2, 3), (0, 3)])
        result = QiskitQAOASolver().solve(
            problem,
            SolverConfig(seed=5, parameters={"p": 1, "optimizer_trials": 4, "shots": 64}),
        )
        self.assertEqual(result.status, SolveStatus.SUCCESS)
        self.assertTrue(result.feasible)
        self.assertTrue(result.backend.is_local)
        self.assertEqual(result.backend.backend_type, "quantum_simulator")
        self.assertEqual(result.backend.name, "qiskit.quantum_info.Statevector")
        self.assertNotIn("job_id", result.backend.metrics)
        self.assertEqual(result.backend.metrics["qubit_count"], 4)

    def test_z_missing_dependency_has_actionable_error(self) -> None:
        # Run after the installed-path test because Qiskit's compiled modules intentionally
        # reject reinitialization in the same process after an interrupted first import.
        problem = MaxCutProblem.generate(4, 0.5, 3)
        with mock.patch.dict(sys.modules, {"qiskit": None}):
            with self.assertRaisesRegex(MissingOptionalDependency, r"\[quantum\]"):
                QiskitQAOASolver().solve(
                    problem,
                    SolverConfig(seed=1, parameters={"optimizer_trials": 2, "shots": 16}),
                )


if __name__ == "__main__":
    unittest.main()
