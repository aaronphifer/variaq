"""Tests for objective-sense handling and historical-run compatibility."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from variaq.analysis.models import AnalysisQuery
from variaq.analysis.operations import analyze_runs
from variaq.experiments.runner import ExperimentRunner
from variaq.experiments.storage import ExperimentStore
from variaq.models import SolverConfig
from variaq.problems.graph_partition import GraphPartitionProblem
from variaq.problems.maxcut import MaxCutProblem
from variaq.solvers.exact import ExactSolver


class MinimizeSenseTests(unittest.TestCase):
    def test_graph_partition_best_is_lowest(self) -> None:
        problem = GraphPartitionProblem.from_edges(
            ["a", "b", "c"],
            [("a", "b", 1.0), ("b", "c", 1.0)],
            partition_count=2,
        )
        with tempfile.TemporaryDirectory() as d:
            store = ExperimentStore(Path(d) / "db.sqlite3")
            runner = ExperimentRunner(store)
            runs = runner.benchmark(problem, [ExactSolver()], {"exact": SolverConfig()})
        result = analyze_runs(runs, AnalysisQuery())
        q = result.groups[0].quality
        self.assertEqual(q.best_objective, 0.0)
        self.assertEqual(q.worst_objective, 0.0)

    def test_maxcut_best_is_highest(self) -> None:
        problem = MaxCutProblem.from_edges(3, [(0, 1, 1.0), (1, 2, 1.0)])
        with tempfile.TemporaryDirectory() as d:
            store = ExperimentStore(Path(d) / "db.sqlite3")
            runner = ExperimentRunner(store)
            runs = runner.benchmark(problem, [ExactSolver()], {"exact": SolverConfig()})
        result = analyze_runs(runs, AnalysisQuery())
        q = result.groups[0].quality
        self.assertEqual(q.best_objective, 2.0)


class HistoricalCompatibilityTests(unittest.TestCase):
    def test_analysis_handles_missing_bqm_metadata(self) -> None:
        problem = MaxCutProblem.from_edges(3, [(0, 1, 1.0), (1, 2, 1.0)])
        with tempfile.TemporaryDirectory() as d:
            store = ExperimentStore(Path(d) / "db.sqlite3")
            runner = ExperimentRunner(store)
            runs = runner.benchmark(problem, [ExactSolver()], {"exact": SolverConfig()})
        # Simulate a historical run by stripping newer metadata fields.
        historical = []
        for run in runs:
            stripped = run.result.backend.metrics.copy()
            for key in [
                "qubit_count",
                "circuit_depth",
                "feasible_sample_count",
                "infeasible_sample_count",
            ]:
                stripped.pop(key, None)
            historical.append(run)
        result = analyze_runs(historical, AnalysisQuery())
        self.assertIsNone(result.groups[0].resource.qubits)
        self.assertIsNone(result.groups[0].feasibility.mean_feasible_rate)


if __name__ == "__main__":
    unittest.main()
