import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from variaq.cli import main
from variaq.problems.base import save_problem
from variaq.problems.maxcut import MaxCutProblem


class CLITests(unittest.TestCase):
    def test_invalid_generation_exits_nonzero(self) -> None:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(stderr):
            code = main(
                [
                    "--problems-dir",
                    directory,
                    "problem",
                    "generate",
                    "maxcut",
                    "--nodes",
                    "0",
                    "--edge-probability",
                    "0.4",
                    "--seed",
                    "1",
                ]
            )
        self.assertNotEqual(code, 0)
        self.assertIn("at least 1", stderr.getvalue())

    def test_generate_solve_list_show_and_reproduce(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            problem_path = root / "problem.json"
            database = root / "runs.sqlite3"
            output = io.StringIO()
            with redirect_stdout(output):
                generate_code = main(
                    [
                        "problem",
                        "generate",
                        "maxcut",
                        "--nodes",
                        "4",
                        "--edge-probability",
                        "0.5",
                        "--seed",
                        "2",
                        "--output",
                        str(problem_path),
                    ]
                )
                solve_code = main(
                    [
                        "--db",
                        str(database),
                        "solve",
                        str(problem_path),
                        "--solver",
                        "exact",
                    ]
                )
            self.assertEqual(generate_code, 0)
            self.assertEqual(solve_code, 0)

            list_output = io.StringIO()
            with redirect_stdout(list_output):
                self.assertEqual(main(["--db", str(database), "runs", "list", "--limit", "5"]), 0)
            self.assertIn('"solver_name": "exact"', list_output.getvalue())

            import json

            run_id = json.loads(list_output.getvalue())["data"][0]["run_id"]
            show_output = io.StringIO()
            with redirect_stdout(show_output):
                self.assertEqual(main(["--db", str(database), "runs", "show", run_id]), 0)
            self.assertIn(run_id, show_output.getvalue())

            reproduce_output = io.StringIO()
            with redirect_stdout(reproduce_output):
                self.assertEqual(main(["--db", str(database), "runs", "reproduce", run_id]), 0)
            self.assertIn(f"reproduced_from={run_id}", reproduce_output.getvalue())

    def test_compare_quantum_rejects_non_qaoa_solver(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            problem_path = root / "problem.json"
            save_problem(MaxCutProblem.from_edges(2, [(0, 1)]), problem_path)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = main(
                    [
                        "--db",
                        str(root / "runs.sqlite3"),
                        "compare",
                        "quantum",
                        str(problem_path),
                        "--solvers",
                        "exact,qaoa",
                    ]
                )
        self.assertEqual(code, 2)
        self.assertIn("QAOA solvers only", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
