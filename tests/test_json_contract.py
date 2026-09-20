"""Tests for the versioned JSON output contract and --json flag behavior."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from variaq.cli import main
from variaq.problems.base import save_problem
from variaq.problems.maxcut import MaxCutProblem


def _qaoa_available() -> bool:
    try:
        import numpy  # noqa: F401
        import qiskit  # noqa: F401

        return True
    except (ImportError, ModuleNotFoundError, RuntimeError):
        return False


QAOA_AVAILABLE = _qaoa_available()


def _capture_json(argv: list[str]) -> tuple[dict, int, str, str]:
    """Run CLI, assert only JSON on stdout, and parse it."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(argv)
    stdout_text = stdout.getvalue()
    assert stdout_text.strip(), "stdout was empty"
    parsed = json.loads(stdout_text)
    assert isinstance(parsed, dict), f"expected envelope object, got {type(parsed)}"
    return parsed, code, stdout_text, stderr.getvalue()


class JsonEnvelopeTests(unittest.TestCase):
    def _problem_and_db(self) -> tuple[Path, Path]:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        problem = MaxCutProblem.from_edges(4, [(0, 1), (1, 2), (2, 3), (0, 3)])
        problem_path = root / "problem.json"
        save_problem(problem, problem_path)
        return problem_path, root / "runs.sqlite3"

    def tearDown(self) -> None:
        if hasattr(self, "_tmp"):
            self._tmp.cleanup()

    def test_solve_json_envelope_fields(self) -> None:
        problem_path, db = self._problem_and_db()
        parsed, code, stdout_text, _ = _capture_json(
            ["--db", str(db), "solve", str(problem_path), "--solver", "exact", "--json"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(parsed["schema_version"], "1")
        self.assertEqual(parsed["command"], "solve")
        self.assertEqual(parsed["status"], "success")
        self.assertIn("run_id", parsed["data"])
        self.assertIn("objective", parsed["data"])
        self.assertEqual(stdout_text, json.dumps(parsed, sort_keys=True) + "\n")

    def test_solve_json_stdout_is_only_json(self) -> None:
        problem_path, db = self._problem_and_db()
        _, _, stdout_text, stderr_text = _capture_json(
            ["--db", str(db), "solve", str(problem_path), "--solver", "exact", "--json"]
        )
        json.loads(stdout_text)
        self.assertNotIn("Saved", stdout_text)
        self.assertNotIn("error", stdout_text)
        # Progress / decorative text should go to stderr, if anywhere.
        self.assertEqual(stderr_text, "")

    def test_benchmark_json_status_and_runs(self) -> None:
        problem_path, db = self._problem_and_db()
        parsed, code, _, _ = _capture_json(
            [
                "--db",
                str(db),
                "benchmark",
                str(problem_path),
                "--solvers",
                "exact,heuristic",
                "--json",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["command"], "benchmark")
        self.assertIn("problem", parsed["data"])
        self.assertEqual(len(parsed["data"]["runs"]), 2)
        self.assertEqual(parsed["data"]["comparison"]["successful_count"], 2)

    def test_benchmark_json_preserves_run_ids(self) -> None:
        problem_path, db = self._problem_and_db()
        parsed, _, _, _ = _capture_json(
            [
                "--db",
                str(db),
                "benchmark",
                str(problem_path),
                "--solvers",
                "exact,heuristic",
                "--json",
            ]
        )
        run_ids = [run["run_id"] for run in parsed["data"]["runs"]]
        self.assertTrue(all(run_id.startswith("run-") for run_id in run_ids))
        self.assertEqual(len(set(run_ids)), len(run_ids))

    @unittest.skipUnless(QAOA_AVAILABLE, "qaoa requires numpy and qiskit")
    def test_compare_quantum_json_returns_coherent_object(self) -> None:
        problem_path, db = self._problem_and_db()
        parsed, code, _, _ = _capture_json(
            [
                "--db",
                str(db),
                "compare",
                "quantum",
                str(problem_path),
                "--solvers",
                "qaoa",
                "--p",
                "1",
                "--optimizer-trials",
                "2",
                "--shots",
                "16",
                "--seed",
                "7",
                "--json",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(parsed["command"], "compare quantum")
        self.assertIn("comparison", parsed["data"])
        self.assertEqual(parsed["data"]["comparison"]["matched_qaoa"], True)
        self.assertEqual(parsed["data"]["runs"][0]["solver"], "qaoa")

    def test_runs_show_json(self) -> None:
        problem_path, db = self._problem_and_db()
        solve_parsed, _, _, _ = _capture_json(
            ["--db", str(db), "solve", str(problem_path), "--solver", "exact", "--json"]
        )
        run_id = solve_parsed["data"]["run_id"]
        show_parsed, code, _, _ = _capture_json(["--db", str(db), "runs", "show", run_id, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(show_parsed["command"], "runs show")
        self.assertEqual(show_parsed["data"]["run_id"], run_id)

    def test_runs_list_json(self) -> None:
        problem_path, db = self._problem_and_db()
        _capture_json(["--db", str(db), "solve", str(problem_path), "--solver", "exact", "--json"])
        parsed, code, _, _ = _capture_json(["--db", str(db), "runs", "list", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(parsed["command"], "runs list")
        self.assertIsInstance(parsed["data"], list)
        self.assertEqual(len(parsed["data"]), 1)
        self.assertEqual(parsed["data"][0]["solver_name"], "exact")

    def test_runs_reproduce_json(self) -> None:
        problem_path, db = self._problem_and_db()
        solve_parsed, _, _, _ = _capture_json(
            ["--db", str(db), "solve", str(problem_path), "--solver", "exact", "--json"]
        )
        run_id = solve_parsed["data"]["run_id"]
        parsed, code, _, _ = _capture_json(["--db", str(db), "runs", "reproduce", run_id, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(parsed["command"], "runs reproduce")
        self.assertEqual(parsed["data"]["original_run_id"], run_id)
        self.assertEqual(parsed["data"]["rerun_of"], run_id)
        self.assertNotEqual(parsed["data"]["new_run_id"], run_id)
        self.assertIn("environment_differences", parsed["data"])

    def test_problem_generate_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parsed, code, stdout_text, _ = _capture_json(
                [
                    "--problems-dir",
                    directory,
                    "problem",
                    "generate",
                    "maxcut",
                    "--nodes",
                    "4",
                    "--edge-probability",
                    "0.5",
                    "--seed",
                    "1",
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(parsed["command"], "problem generate")
        self.assertEqual(parsed["data"]["problem_type"], "maxcut")
        self.assertEqual(parsed["data"]["node_count"], 4)
        self.assertEqual(stdout_text, json.dumps(parsed, sort_keys=True) + "\n")

    def test_problem_show_json(self) -> None:
        problem_path, _ = self._problem_and_db()
        parsed, code, _, _ = _capture_json(["problem", "show", str(problem_path), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(parsed["command"], "problem show")
        self.assertEqual(parsed["data"]["problem_type"], "maxcut")

    def test_error_json_returns_structured_error(self) -> None:
        problem_path, db = self._problem_and_db()
        parsed, code, stdout_text, _ = _capture_json(
            [
                "--db",
                str(db),
                "solve",
                str(problem_path),
                "--solver",
                "exact",
                "--param",
                "max_variables=2",
                "--json",
            ]
        )
        self.assertEqual(code, 1)
        self.assertEqual(parsed["status"], "error")
        self.assertEqual(parsed["command"], "solve")
        self.assertIn("error", parsed)
        self.assertIn("run_id", parsed["error"])
        self.assertIn("data", parsed)
        self.assertEqual(stdout_text, json.dumps(parsed, sort_keys=True) + "\n")

    def test_invalid_input_json_returns_error_envelope(self) -> None:
        parsed, code, stdout_text, _ = _capture_json(
            [
                "problem",
                "generate",
                "maxcut",
                "--nodes",
                "0",
                "--edge-probability",
                "0.4",
                "--seed",
                "1",
                "--json",
            ]
        )
        self.assertEqual(code, 2)
        self.assertEqual(parsed["status"], "error")
        self.assertIn("error", parsed)
        self.assertEqual(stdout_text, json.dumps(parsed, sort_keys=True) + "\n")

    def test_capabilities_json(self) -> None:
        parsed, code, _, _ = _capture_json(["capabilities", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(parsed["schema_version"], "1")
        self.assertEqual(parsed["command"], "capabilities")
        self.assertIn("variaq", parsed["data"])
        self.assertIn("output_schema_version", parsed["data"]["variaq"])
        solver_names = {solver["name"] for solver in parsed["data"]["solvers"]}
        self.assertTrue({"exact", "heuristic", "qaoa", "cudaq-cpu", "cudaq-gpu"} <= solver_names)

    @unittest.skipUnless(QAOA_AVAILABLE, "qaoa requires numpy and qiskit")
    def test_no_numpy_values_leak_into_json(self) -> None:
        problem_path, db = self._problem_and_db()
        parsed, _, stdout_text, _ = _capture_json(
            [
                "--db",
                str(db),
                "compare",
                "quantum",
                str(problem_path),
                "--solvers",
                "qaoa",
                "--p",
                "1",
                "--optimizer-trials",
                "2",
                "--shots",
                "8",
                "--seed",
                "5",
                "--json",
            ]
        )
        self.assertNotIn("np.float", stdout_text)
        self.assertNotIn("numpy(", stdout_text)
        # candidate_expectations should be plain floats.
        expectations = parsed["data"]["runs"][0]["backend_metadata"]["metrics"][
            "candidate_expectations"
        ]
        self.assertTrue(all(isinstance(value, float) for value in expectations))

    def test_json_failure_path_preserves_run_id(self) -> None:
        problem_path, db = self._problem_and_db()
        parsed, code, _, _ = _capture_json(
            [
                "--db",
                str(db),
                "solve",
                str(problem_path),
                "--solver",
                "exact",
                "--param",
                "max_variables=2",
                "--json",
            ]
        )
        self.assertEqual(code, 1)
        self.assertEqual(parsed["status"], "error")
        self.assertTrue(parsed["error"]["run_id"].startswith("run-"))

    def test_unknown_run_json_error(self) -> None:
        _, db = self._problem_and_db()
        parsed, code, _, _ = _capture_json(
            ["--db", str(db), "runs", "show", "run-does-not-exist", "--json"]
        )
        self.assertEqual(code, 2)
        self.assertEqual(parsed["status"], "error")
        self.assertEqual(parsed["error"]["type"], "ValidationError")

    def test_benchmark_partial_status_on_mixed_outcomes(self) -> None:
        problem_path, db = self._problem_and_db()
        parsed, code, _, _ = _capture_json(
            [
                "--db",
                str(db),
                "benchmark",
                str(problem_path),
                "--solvers",
                "exact,cudaq-gpu",
                "--json",
            ]
        )
        # exact succeeds; cudaq-gpu is unavailable on this host if no GPU, so
        # aggregate status is partial. If GPU is present, test may see success.
        self.assertIn(parsed["data"]["comparison"]["aggregate_status"], ("success", "partial"))
        self.assertEqual(parsed["command"], "benchmark")


class JsonStdoutOnlyTests(unittest.TestCase):
    def test_pipe_to_jq_compatible(self) -> None:
        problem = MaxCutProblem.from_edges(4, [(0, 1), (1, 2), (2, 3), (0, 3)])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            problem_path = root / "problem.json"
            db = root / "runs.sqlite3"
            save_problem(problem, problem_path)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "variaq",
                    "--db",
                    str(db),
                    "solve",
                    str(problem_path),
                    "--solver",
                    "exact",
                    "--json",
                ],
                capture_output=True,
                text=True,
                cwd=str(Path(__file__).resolve().parents[1]),
            )
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "success")
            self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
