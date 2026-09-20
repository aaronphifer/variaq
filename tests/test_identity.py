import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

import variaq
from variaq.cli import DEFAULT_DB, LEGACY_DEFAULT_DB, _default_db_path, main
from variaq.experiments.runner import ExperimentRunner
from variaq.experiments.storage import ExperimentStore
from variaq.models import SolverConfig
from variaq.problems.maxcut import MaxCutProblem
from variaq.solvers.exact import ExactMaxCutSolver


class PublicIdentityTests(unittest.TestCase):
    def test_variaq_import_and_version(self) -> None:
        self.assertEqual(variaq.__version__, "0.4.0")

    def test_module_help_uses_public_cli_name(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "variaq", "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("usage: variaq"))
        self.assertIn("compare", result.stdout)

    def test_main_help_exits_successfully(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("usage: variaq", output.getvalue())

    def test_legacy_default_database_is_discovered_without_migration(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                LEGACY_DEFAULT_DB.parent.mkdir(parents=True)
                LEGACY_DEFAULT_DB.touch()
                self.assertEqual(_default_db_path(), LEGACY_DEFAULT_DB)
                DEFAULT_DB.touch()
                self.assertEqual(_default_db_path(), DEFAULT_DB)
            finally:
                os.chdir(original)

    def test_historical_environment_metadata_reads_and_reproduces(self) -> None:
        problem = MaxCutProblem.from_edges(3, [(0, 1), (1, 2)])
        with tempfile.TemporaryDirectory() as directory:
            store = ExperimentStore(Path(directory) / "runs.sqlite3")
            runner = ExperimentRunner(store)
            current = runner.run_one(problem, ExactMaxCutSolver(), SolverConfig(seed=42))
            historical = replace(
                current,
                run_id="run-historical-q-lab-v02",
                environment={"packages": {"q-lab": "0.3.0"}},
            )
            store.save(historical)
            loaded = store.get(historical.run_id)
            reproduced = runner.reproduce(historical.run_id)

        self.assertEqual(loaded.environment["packages"]["q-lab"], "0.3.0")
        self.assertEqual(reproduced.rerun_of, historical.run_id)
        self.assertEqual(reproduced.result.objective, historical.result.objective)
        self.assertNotEqual(reproduced.run_id, historical.run_id)


if __name__ == "__main__":
    unittest.main()
