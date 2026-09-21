"""Tests for the VariaQ 0.6 analysis layer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from variaq.analysis.metrics import (
    approximation_ratio,
    best_known_objective,
    make_repeat_summary,
    relative_gap,
)
from variaq.analysis.models import AnalysisQuery
from variaq.analysis.operations import analyze_runs
from variaq.analysis.reports import export_report, generate_report
from variaq.campaigns.model import ExperimentCampaign
from variaq.campaigns.runner import CampaignRunner
from variaq.campaigns.store import CampaignStore
from variaq.experiments.runner import ExperimentRunner
from variaq.experiments.storage import ExperimentStore
from variaq.models import BackendMetadata, SolverConfig, SolveResult, SolveStatus
from variaq.problems.maxcut import MaxCutProblem
from variaq.solvers.base import Solver
from variaq.solvers.exact import ExactSolver


class RepeatSummaryTests(unittest.TestCase):
    def test_empty(self) -> None:
        summary = make_repeat_summary([])
        self.assertEqual(summary.count, 0)
        self.assertIsNone(summary.mean)

    def test_one_observation(self) -> None:
        summary = make_repeat_summary([3.0])
        self.assertEqual(summary.count, 1)
        self.assertIsNone(summary.std)
        self.assertEqual(summary.mean, 3.0)

    def test_basic_statistics(self) -> None:
        summary = make_repeat_summary([1.0, 2.0, 3.0, 4.0])
        self.assertEqual(summary.count, 4)
        self.assertAlmostEqual(summary.mean, 2.5)  # type: ignore[arg-type]
        self.assertEqual(summary.minimum, 1.0)
        self.assertEqual(summary.maximum, 4.0)

    def test_ignores_none(self) -> None:
        summary = make_repeat_summary([1.0, None, 3.0])
        self.assertEqual(summary.count, 2)
        self.assertEqual(summary.mean, 2.0)


class ObjectiveSenseTests(unittest.TestCase):
    def test_maximize_best(self) -> None:
        problem = MaxCutProblem.from_edges(3, [(0, 1, 1.0), (1, 2, 1.0)])
        with tempfile.TemporaryDirectory() as d:
            store = ExperimentStore(Path(d) / "db.sqlite3")
            runner = ExperimentRunner(store)
            runs = runner.benchmark(problem, [ExactSolver()], {"exact": SolverConfig()})
        best, source = best_known_objective(runs)
        self.assertEqual(best, 2.0)
        self.assertEqual(source, "exact_optimum")

    def test_minimize_gap(self) -> None:
        gap = relative_gap(10.0, 12.0)
        self.assertEqual(gap, 20.0)
        ratio = approximation_ratio(10.0, 12.0, "minimize")  # type: ignore[arg-type]
        self.assertAlmostEqual(ratio, 10.0 / 12.0)  # type: ignore[arg-type]


class FeasibilityAnalysisTests(unittest.TestCase):
    def test_group_feasibility_statistics(self) -> None:
        problem = MaxCutProblem.from_edges(3, [(0, 1, 1.0), (1, 2, 1.0)])
        with tempfile.TemporaryDirectory() as d:
            store = ExperimentStore(Path(d) / "db.sqlite3")
            runner = ExperimentRunner(store)
            runs = runner.benchmark(
                problem,
                [FeasibleFakeSolver()],
                {"fake": SolverConfig()},
                repeats=3,
            )
        result = analyze_runs(runs, AnalysisQuery())
        self.assertEqual(result.groups[0].feasibility.feasible_runs, 3)
        self.assertEqual(result.groups[0].feasibility.zero_feasible_runs, 0)
        self.assertEqual(result.groups[0].feasibility.mean_feasible_rate, 1.0)


class FeasibleFakeSolver(Solver):
    name = "fake"
    version = "test"
    supported_families = frozenset({"maxcut"})

    def solve(self, problem, config):
        return SolveResult(
            solver_name=self.name,
            solver_version=self.version,
            problem_id=problem.problem_id,
            problem_type=problem.problem_type,
            variable_count=problem.variable_count,
            solution=(0, 1, 0),
            objective=2.0,
            feasible=True,
            constraint_violations=(),
            wall_time_seconds=0.0,
            solver_time_seconds=0.0,
            backend=BackendMetadata(
                backend_type="classical_cpu",
                name="test",
                provider="test",
                is_local=True,
                metrics={"feasible_sample_count": 100, "infeasible_sample_count": 0},
            ),
            seed=0,
            parameters={},
            timestamp="t",
            status=SolveStatus.SUCCESS,
        )


class CampaignAnalysisEndToEndTests(unittest.TestCase):
    def test_tiny_maxcut_campaign_analyzes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            exp_store = ExperimentStore(root / "runs.sqlite3")
            runner = ExperimentRunner(exp_store)
            camp_store = CampaignStore(root / "runs.sqlite3")
            problems_dir = root / "problems"
            problems_dir.mkdir()
            campaign = ExperimentCampaign(
                name="tiny",
                family="maxcut",
                problem_sizes=(4, 6),
                problem_seeds=(1,),
                solvers=("exact", "heuristic"),
                repeats=2,
            )
            cr = CampaignRunner(runner, camp_store, problems_dir, max_runs=1000)
            summary = cr.run(campaign)
            self.assertEqual(summary["requested_runs"], 8)
            self.assertEqual(summary["completed_runs"], 8)

            run_ids = camp_store.get_run_ids(summary["campaign_id"])
            self.assertEqual(len(run_ids), 8)
            runs = [exp_store.get(rid) for rid in run_ids]
            result = analyze_runs(
                runs,
                AnalysisQuery(group_by=("problem_id", "solver")),
                scaling_x_metric="problem_size",
            )
            self.assertGreaterEqual(len(result.groups), 2)
            self.assertEqual(set(result.source_run_ids), set(run_ids))

            report = generate_report(result, campaign_id=summary["campaign_id"])
            paths = export_report(report, root / "reports")
            self.assertIn("json", paths)
            self.assertIn("markdown", paths)


if __name__ == "__main__":
    unittest.main()
