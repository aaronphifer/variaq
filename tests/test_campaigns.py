"""Tests for campaign planning, execution, and safety guards."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from variaq.campaigns.model import ExperimentCampaign, SolverOverride
from variaq.campaigns.plan import CampaignPlan
from variaq.campaigns.runner import CampaignRunner
from variaq.campaigns.store import CampaignStore
from variaq.errors import ValidationError
from variaq.experiments.runner import ExperimentRunner
from variaq.experiments.storage import ExperimentStore
from variaq.models import SolverConfig
from variaq.solvers.base import Solver
from variaq.solvers.exact import ExactSolver


class CampaignIdentityTests(unittest.TestCase):
    def test_id_is_deterministic(self) -> None:
        from variaq.campaigns.model import campaign_definition_id

        a = ExperimentCampaign(
            name="scale",
            family="maxcut",
            problem_sizes=(4, 6),
            problem_seeds=(1, 2),
            solvers=("exact",),
        )
        b = ExperimentCampaign(
            name="scale",
            family="maxcut",
            problem_sizes=(4, 6),
            problem_seeds=(1, 2),
            solvers=("exact",),
        )
        self.assertEqual(campaign_definition_id(a), campaign_definition_id(b))

    def test_id_changes_with_content(self) -> None:
        from variaq.campaigns.model import campaign_definition_id

        a = ExperimentCampaign(
            name="scale",
            family="maxcut",
            problem_sizes=(4, 6),
            problem_seeds=(1, 2),
            solvers=("exact",),
        )
        b = ExperimentCampaign(
            name="scale",
            family="maxcut",
            problem_sizes=(4, 8),
            problem_seeds=(1, 2),
            solvers=("exact",),
        )
        self.assertNotEqual(campaign_definition_id(a), campaign_definition_id(b))


class CampaignValidationTests(unittest.TestCase):
    def test_rejects_unknown_solver(self) -> None:
        with self.assertRaises(ValidationError):
            ExperimentCampaign(
                name="bad",
                family="maxcut",
                problem_sizes=(4,),
                problem_seeds=(1,),
                solvers=("magic",),
            )

    def test_rejects_solver_config_for_unselected_solver(self) -> None:
        with self.assertRaises(ValidationError):
            ExperimentCampaign(
                name="bad",
                family="maxcut",
                problem_sizes=(4,),
                problem_seeds=(1,),
                solvers=("exact",),
                solver_config={"qaoa": SolverOverride(parameters={})},
            )


class CampaignPlanTests(unittest.TestCase):
    def test_plan_counts_runs(self) -> None:
        campaign = ExperimentCampaign(
            name="scale",
            family="maxcut",
            problem_sizes=(4, 6),
            problem_seeds=(1, 2),
            solvers=("exact", "heuristic"),
            repeats=3,
        )
        plan = CampaignPlan(campaign).build()
        self.assertEqual(plan["requested_runs"], 24)
        self.assertEqual(plan["problem_instance_count"], 4)


class CampaignRunnerTests(unittest.TestCase):
    def test_tiny_campaign_executes_expected_runs(self) -> None:
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
            self.assertIn("success", summary["status_summary"])
            self.assertEqual(summary["status_summary"]["success"], 8)
            self.assertEqual(len(camp_store.get_run_ids(summary["campaign_id"])), 8)

    def test_max_runs_guard(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            exp_store = ExperimentStore(root / "runs.sqlite3")
            runner = ExperimentRunner(exp_store)
            camp_store = CampaignStore(root / "runs.sqlite3")
            problems_dir = root / "problems"
            problems_dir.mkdir()
            campaign = ExperimentCampaign(
                name="big",
                family="maxcut",
                problem_sizes=tuple(range(1, 50)),
                problem_seeds=(1, 2, 3),
                solvers=("exact", "heuristic"),
                repeats=5,
            )
            cr = CampaignRunner(runner, camp_store, problems_dir, max_runs=10)
            with self.assertRaises(ValidationError):
                cr.run(campaign)

    def test_override_max_runs(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            exp_store = ExperimentStore(root / "runs.sqlite3")
            runner = ExperimentRunner(exp_store)
            camp_store = CampaignStore(root / "runs.sqlite3")
            problems_dir = root / "problems"
            problems_dir.mkdir()
            campaign = ExperimentCampaign(
                name="override",
                family="maxcut",
                problem_sizes=(4, 6),
                problem_seeds=(1,),
                solvers=("exact",),
                repeats=1,
            )
            cr = CampaignRunner(runner, camp_store, problems_dir, max_runs=1)
            summary = cr.run(campaign, override_max_runs=True)
            self.assertEqual(summary["requested_runs"], 2)

    def test_failure_is_isolated(self) -> None:
        class SometimesFailingSolver(Solver):
            name = "sometimes-failing"
            version = "test"
            supported_families = frozenset({"maxcut"})
            call_count = 0

            def solve(self, problem, config):
                SometimesFailingSolver.call_count += 1
                if SometimesFailingSolver.call_count > 1:
                    raise RuntimeError("intentional failure")
                return ExactSolver().solve(problem, config)

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            exp_store = ExperimentStore(root / "runs.sqlite3")
            runner = ExperimentRunner(exp_store)
            camp_store = CampaignStore(root / "runs.sqlite3")
            problems_dir = root / "problems"
            problems_dir.mkdir()
            campaign = ExperimentCampaign(
                name="failing",
                family="maxcut",
                problem_sizes=(4,),
                problem_seeds=(1,),
                solvers=("exact",),
                repeats=2,
            )
            cr = CampaignRunner(runner, camp_store, problems_dir, max_runs=1000)
            # Monkey-patch runner to simulate a single solver failure on repeat.
            original_benchmark = runner.benchmark

            def failing_benchmark(problem, solvers, configs, repeats=1):
                runs = original_benchmark(problem, solvers, configs, repeats=repeats)
                # Force the second run to fail by re-running with a failing solver.
                failing = type(
                    "F",
                    (Solver,),
                    {
                        "name": "failing-injected",
                        "version": "test",
                        "supported_families": frozenset({"maxcut"}),
                        "solve": lambda self, p, c: (_ for _ in ()).throw(RuntimeError("injected")),
                    },
                )()
                return runs[:1] + [
                    runner._execute(problem, failing, configs.get("exact", SolverConfig()), None)
                ]

            runner.benchmark = failing_benchmark
            summary = cr.run(campaign)
            self.assertGreaterEqual(summary["status_summary"].get("success", 0), 1)
            self.assertGreaterEqual(summary["status_summary"].get("failed", 0), 1)


if __name__ == "__main__":
    unittest.main()
