import sqlite3
import tempfile
import unittest
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from variaq.errors import BackendUnavailableError, DuplicateRunError
from variaq.experiments.runner import ExperimentRunner
from variaq.experiments.storage import ExperimentStore
from variaq.models import BackendMetadata, SolverConfig, SolveResult, SolveStatus, utc_now
from variaq.problems.base import ProblemInstance
from variaq.problems.maxcut import MaxCutProblem
from variaq.solvers.base import Solver
from variaq.solvers.exact import ExactMaxCutSolver
from variaq.solvers.heuristic import HeuristicMaxCutSolver


class FailingSolver(Solver):
    name = "failing-test-solver"
    version = "test"

    def solve(self, problem: ProblemInstance, config: SolverConfig) -> SolveResult:
        raise RuntimeError("intentional solver failure")


class RemotePretenderSolver(Solver):
    name = "remote-test-solver"
    version = "test"

    def solve(self, problem: ProblemInstance, config: SolverConfig) -> SolveResult:
        return SolveResult(
            solver_name=self.name,
            solver_version=self.version,
            problem_id=problem.problem_id,
            problem_type=problem.problem_type,
            variable_count=problem.variable_count,
            solution=tuple(0 for _ in range(problem.variable_count)),
            objective=0.0,
            feasible=True,
            constraint_violations=(),
            wall_time_seconds=0.0,
            solver_time_seconds=0.0,
            backend=BackendMetadata(
                backend_type="qpu", name="forbidden", provider="test", is_local=False
            ),
            seed=config.seed,
            parameters={},
            timestamp=utc_now(),
            status=SolveStatus.SUCCESS,
        )


class UnavailableSolver(Solver):
    name = "unavailable-test-solver"
    version = "test"

    def solve(self, problem: ProblemInstance, config: SolverConfig) -> SolveResult:
        raise BackendUnavailableError(
            "intentional unavailable backend",
            backend_name="unavailable-test-backend",
            provider="test",
        )


class ExperimentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = ExperimentStore(Path(self.temporary_directory.name) / "runs.sqlite3")
        self.runner = ExperimentRunner(self.store)
        self.problem = MaxCutProblem.generate(6, 0.5, 42)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_solver_failure_is_structured_and_persisted(self) -> None:
        run = self.runner.run_one(self.problem, FailingSolver(), SolverConfig(seed=3))
        self.assertEqual(run.result.status, SolveStatus.FAILED)
        self.assertIn("intentional solver failure", run.result.errors[0])
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.get(run.run_id), run)

    def test_duplicate_run_cannot_overwrite(self) -> None:
        run = self.runner.run_one(self.problem, ExactMaxCutSolver(), SolverConfig())
        with self.assertRaises(DuplicateRunError):
            self.store.save(run)
        self.assertEqual(self.store.count(), 1)

    def test_remote_backend_is_rejected_and_recorded_as_failure(self) -> None:
        run = self.runner.run_one(self.problem, RemotePretenderSolver(), SolverConfig())
        self.assertEqual(run.result.status, SolveStatus.FAILED)
        self.assertIn("refuses non-local backends", run.result.errors[0])
        self.assertEqual(self.store.count(), 1)

    def test_benchmark_uses_exact_optimum_for_all_gaps(self) -> None:
        runs = self.runner.benchmark(
            self.problem,
            [ExactMaxCutSolver(), HeuristicMaxCutSolver()],
            {
                "exact": SolverConfig(seed=7),
                "heuristic": SolverConfig(seed=7, parameters={"restarts": 4}),
            },
        )
        exact = next(run for run in runs if run.result.solver_name == "exact")
        self.assertEqual(exact.result.best_known_source, "exact_optimum")
        self.assertEqual(exact.result.optimality_gap_percent, 0.0)
        self.assertTrue(
            all(run.result.best_known_objective == exact.result.objective for run in runs)
        )
        self.assertEqual(self.store.count(), 2)

    def test_run_ids_are_independent_even_for_same_configuration(self) -> None:
        first = self.runner.run_one(self.problem, HeuristicMaxCutSolver(), SolverConfig(seed=5))
        second = self.runner.run_one(self.problem, HeuristicMaxCutSolver(), SolverConfig(seed=5))
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(first.result.solution, second.result.solution)

    def test_mutated_problem_snapshot_is_rejected_for_same_id(self) -> None:
        run = self.runner.run_one(self.problem, ExactMaxCutSolver(), SolverConfig())
        altered = dict(run.problem)
        altered["node_count"] = int(altered["node_count"]) + 1
        with self.assertRaisesRegex(Exception, "does not match content"):
            self.store.save(replace(run, run_id="run-new", problem=altered))


class StorageLifecycleTests(unittest.TestCase):
    def _assert_database_removable(self, operation: Callable[[ExperimentRunner], None]) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "runs.sqlite3"
            store = ExperimentStore(database)
            runner = ExperimentRunner(store)
            operation(runner)
            self.assertTrue(database.exists())
            database.unlink()
            self.assertFalse(database.exists())

    def test_storage_connection_is_closed_after_its_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ExperimentStore(Path(directory) / "runs.sqlite3")
            with store._connection() as connection:
                connection.execute("SELECT 1").fetchone()
            with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed database"):
                connection.execute("SELECT 1")

    def test_database_is_removable_after_successful_run(self) -> None:
        problem = MaxCutProblem.from_edges(3, [(0, 1), (1, 2)])
        self._assert_database_removable(
            lambda runner: runner.run_one(problem, ExactMaxCutSolver(), SolverConfig(seed=1))
        )

    def test_database_is_removable_after_failed_run(self) -> None:
        problem = MaxCutProblem.from_edges(2, [(0, 1)])
        self._assert_database_removable(
            lambda runner: runner.run_one(problem, FailingSolver(), SolverConfig(seed=2))
        )

    def test_database_is_removable_after_unavailable_run(self) -> None:
        problem = MaxCutProblem.from_edges(2, [(0, 1)])
        self._assert_database_removable(
            lambda runner: runner.run_one(problem, UnavailableSolver(), SolverConfig(seed=3))
        )

    def test_database_is_removable_after_reproduction(self) -> None:
        problem = MaxCutProblem.from_edges(3, [(0, 1), (1, 2), (0, 2)])

        def reproduce(runner: ExperimentRunner) -> None:
            original = runner.run_one(problem, ExactMaxCutSolver(), SolverConfig(seed=4))
            reproduced = runner.reproduce(original.run_id)
            self.assertEqual(reproduced.rerun_of, original.run_id)

        self._assert_database_removable(reproduce)


if __name__ == "__main__":
    unittest.main()
