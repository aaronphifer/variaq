from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from variaq import lower
from variaq.errors import ValidationError
from variaq.lower import lower_to_binary_quadratic
from variaq.models import OptimizationSense, SolverConfig
from variaq.problems.assignment import AssignmentProblem
from variaq.problems.graph_partition import GraphPartitionProblem
from variaq.problems.maxcut import MaxCutProblem
from variaq.problems.subset_selection import SubsetSelectionProblem

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
from adapters.task_assignment.adapter import TaskWorkerAdapter, Worker, WorkItem  # noqa: E402


class LoweringTests(unittest.TestCase):
    def test_maxcut_lower_matches_evaluator_on_known_solution(self) -> None:
        triangle = MaxCutProblem.from_edges(3, [(0, 1), (1, 2), (0, 2)])
        model = lower_to_binary_quadratic(triangle)
        best = None
        best_obj = float("-inf")
        for state in _states(3):
            state_map = dict(zip(model.variable_ids, state, strict=True))
            decoded = lower.decode_solution(model, state_map)
            evaluation = triangle.evaluate(decoded)
            if (
                evaluation.feasible
                and evaluation.objective is not None
                and evaluation.objective > best_obj
            ):
                best_obj = evaluation.objective
                best = state
        assert best is not None
        best_map = dict(zip(model.variable_ids, best, strict=True))
        decoded = lower.decode_solution(model, best_map)
        evaluation = triangle.evaluate(decoded)
        self.assertTrue(evaluation.feasible)
        self.assertEqual(evaluation.objective, 2.0)

    def test_assignment_lower_decodes_to_feasible_solution(self) -> None:
        problem = AssignmentProblem.from_score_matrix(
            ["t1", "t2"],
            ["r1", "r2"],
            {("t1", "r1"): 5.0, ("t1", "r2"): 1.0, ("t2", "r1"): 2.0, ("t2", "r2"): 4.0},
        )
        model = lower_to_binary_quadratic(problem)
        # Brute force best feasible state
        best = None
        best_score = float("inf")
        for state in _states(len(model.variable_ids)):
            state_map = dict(zip(model.variable_ids, state, strict=True))
            decoded = lower.decode_solution(model, state_map)
            evaluation = problem.evaluate(decoded)
            if evaluation.feasible and evaluation.objective is not None:
                if evaluation.objective < best_score:
                    best_score = evaluation.objective
                    best = state
        assert best is not None
        best_map = dict(zip(model.variable_ids, best, strict=True))
        decoded = lower.decode_solution(model, best_map)
        evaluation = problem.evaluate(decoded)
        self.assertTrue(evaluation.feasible)
        self.assertEqual(evaluation.objective, best_score)

    def test_subset_lower_respects_interactions(self) -> None:
        problem = SubsetSelectionProblem.from_data(
            ["a", "b"],
            {"a": 1.0, "b": 1.0},
            interaction={frozenset({"a", "b"}): 10.0},
        )
        model = lower_to_binary_quadratic(problem)
        best = None
        best_score = float("-inf")
        for state in _states(len(model.variable_ids)):
            state_map = dict(zip(model.variable_ids, state, strict=True))
            decoded = lower.decode_solution(model, state_map)
            evaluation = problem.evaluate(decoded)
            if evaluation.feasible and evaluation.objective is not None:
                if evaluation.objective > best_score:
                    best_score = evaluation.objective
                    best = state
        assert best is not None
        self.assertEqual(set(problem.candidate_ids), {"a", "b"})
        self.assertEqual(best_score, 12.0)

    def test_unknown_family_is_rejected(self) -> None:
        from variaq.problems.base import ProblemInstance

        class DummyProblem(ProblemInstance):
            problem_id = "dummy"
            problem_type = "dummy"
            family = "dummy"
            schema_version = 1
            sense = OptimizationSense.MAXIMIZE

            @property
            def variable_count(self) -> int:
                return 1

            def evaluate(self, solution):
                from variaq.models import Evaluation

                return Evaluation(objective=0.0, feasible=True)

            def to_dict(self):
                return {}

            def identity_payload(self):
                return {}

        dummy = DummyProblem()
        with self.assertRaises(ValidationError):
            lower_to_binary_quadratic(dummy)


class AdapterTests(unittest.TestCase):
    def test_adapter_round_trip_with_generated_problem(self) -> None:
        items = [
            WorkItem("item-a", "network"),
            WorkItem("item-b", "database"),
        ]
        workers = [
            Worker("worker-1", {"network"}),
            Worker("worker-2", {"database"}),
        ]
        adapter = TaskWorkerAdapter()
        problem = adapter.to_variaq((items, workers))
        self.assertEqual(problem.family, "assignment")
        self.assertIn(("item-a", "worker-1"), problem.score)
        self.assertIn(("item-b", "worker-2"), problem.score)
        self.assertEqual(len(problem.prohibited), 2)

    def test_adapter_scaffold_creates_expected_files(self) -> None:
        from variaq.adapter_scaffold import init_adapter

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "my-adapter"
            paths = init_adapter("my-adapter", "assignment", target)
            self.assertEqual(len(paths), 3)
            self.assertTrue(all(p.exists() for p in paths))
            self.assertIn("DomainAdapter", target.joinpath("adapter.py").read_text())
            self.assertNotIn("triagewall", target.joinpath("adapter.py").read_text().lower())
            self.assertNotIn("ollama", target.joinpath("adapter.py").read_text().lower())


class FamilyProblemTests(unittest.TestCase):
    def test_assignment_round_trip(self) -> None:
        problem = AssignmentProblem.generate(3, 2, 42)
        serialized = problem.to_dict()
        loaded = AssignmentProblem.from_dict(serialized)
        self.assertEqual(problem, loaded)
        self.assertEqual(problem.problem_id, loaded.problem_id)

    def test_assignment_evaluator_known_optimum(self) -> None:
        problem = AssignmentProblem.from_score_matrix(
            ["t1", "t2"],
            ["r1", "r2"],
            {("t1", "r1"): 5.0, ("t1", "r2"): 1.0, ("t2", "r1"): 2.0, ("t2", "r2"): 4.0},
        )
        # Optimal assignment: t1->r1, t2->r2 = 9
        evaluation = problem.evaluate((1, 0, 0, 1))
        self.assertTrue(evaluation.feasible)
        self.assertEqual(evaluation.objective, 9.0)

    def test_subset_round_trip_and_optimum(self) -> None:
        problem = SubsetSelectionProblem.from_data(
            ["a", "b", "c"],
            {"a": 1.0, "b": 2.0, "c": 3.0},
        )
        serialized = problem.to_dict()
        loaded = SubsetSelectionProblem.from_dict(serialized)
        self.assertEqual(problem, loaded)
        self.assertEqual(problem.evaluate((0, 1, 1)).objective, 5.0)

    def test_graph_partition_round_trip_and_optimum(self) -> None:
        # A square with one diagonal; optimal 2-partition keeps diagonal inside.
        problem = GraphPartitionProblem.from_edges(
            ["a", "b", "c", "d"],
            [("a", "b", 1.0), ("b", "c", 1.0), ("c", "d", 1.0), ("d", "a", 1.0), ("a", "c", 10.0)],
            2,
        )
        # Partition {a,c} | {b,d}: crossing edges ab, bc, cd, da = 4; diagonal ac internal
        solution = (1, 0, 0, 1, 1, 0, 0, 1)
        evaluation = problem.evaluate(solution)
        self.assertTrue(evaluation.feasible)
        self.assertEqual(evaluation.objective, 4.0)

    def test_objective_sense_affects_metrics(self) -> None:
        from variaq.experiments.runner import ExperimentRunner
        from variaq.experiments.storage import ExperimentStore
        from variaq.models import SolverConfig
        from variaq.solvers.exact import ExactSolver

        maximize = SubsetSelectionProblem.from_data(
            ["a", "b"], {"a": 10.0, "b": 1.0}, sense=OptimizationSense.MAXIMIZE
        )
        minimize = SubsetSelectionProblem.from_data(
            ["a", "b"], {"a": 10.0, "b": 1.0}, sense=OptimizationSense.MINIMIZE
        )
        with tempfile.TemporaryDirectory() as directory:
            store = ExperimentStore(Path(directory) / "runs.sqlite3")
            runner = ExperimentRunner(store)
            max_run = runner.run_one(maximize, ExactSolver(), SolverConfig(seed=1))
            min_run = runner.run_one(minimize, ExactSolver(), SolverConfig(seed=1))
        self.assertEqual(max_run.result.objective, 11.0)
        self.assertEqual(min_run.result.objective, 0.0)
        self.assertEqual(max_run.result.optimality_gap_percent, 0.0)
        self.assertEqual(min_run.result.optimality_gap_percent, 0.0)

    def test_solver_rejects_unsupported_family(self) -> None:
        from variaq.errors import ValidationError
        from variaq.solvers.qiskit_qaoa import QiskitQAOASolver

        # Verify the solver's family check is enforced by patching
        # supported_families to a smaller set.
        problem = AssignmentProblem.generate(2, 2, 1)
        solver = QiskitQAOASolver()
        solver.supported_families = frozenset({"maxcut"})
        with self.assertRaises(ValidationError):
            solver.solve(problem, SolverConfig(seed=1))


def _states(n: int):
    for state in range(1 << n):
        yield tuple((state >> i) & 1 for i in range(n))


if __name__ == "__main__":
    unittest.main()
