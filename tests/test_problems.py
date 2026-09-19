import json
import tempfile
import unittest
from pathlib import Path

from variaq.errors import ValidationError
from variaq.problems.base import load_problem, save_problem
from variaq.problems.maxcut import MaxCutProblem


class MaxCutProblemTests(unittest.TestCase):
    def test_serialization_round_trip_is_exact(self) -> None:
        problem = MaxCutProblem.generate(8, 0.4, 42)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "problem.json"
            save_problem(problem, path)
            loaded = load_problem(path)
        self.assertEqual(problem, loaded)
        self.assertEqual(problem.to_dict(), loaded.to_dict())

    def test_content_tampering_is_rejected(self) -> None:
        problem = MaxCutProblem.generate(5, 0.6, 7)
        document = problem.to_dict()
        document["node_count"] = 6
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "problem.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "does not match content"):
                load_problem(path)

    def test_evaluator_is_authoritative_and_flags_invalid_solutions(self) -> None:
        triangle = MaxCutProblem.from_edges(3, [(0, 1), (1, 2), (0, 2)])
        valid = triangle.evaluate((0, 1, 0))
        self.assertTrue(valid.feasible)
        self.assertEqual(valid.objective, 2.0)

        wrong_length = triangle.evaluate((0, 1))
        self.assertFalse(wrong_length.feasible)
        self.assertIsNone(wrong_length.objective)
        self.assertTrue(wrong_length.constraint_violations)

        non_binary = triangle.evaluate((0, 2, 1))
        self.assertFalse(non_binary.feasible)
        self.assertIn("non-binary", non_binary.constraint_violations[0])

    def test_seeded_generation_is_repeatable(self) -> None:
        first = MaxCutProblem.generate(10, 0.4, 42)
        second = MaxCutProblem.generate(10, 0.4, 42)
        different = MaxCutProblem.generate(10, 0.4, 43)
        self.assertEqual(first, second)
        self.assertNotEqual(first.problem_id, different.problem_id)

    def test_save_refuses_overwrite(self) -> None:
        problem = MaxCutProblem.generate(4, 0.5, 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "problem.json"
            save_problem(problem, path)
            with self.assertRaises(FileExistsError):
                save_problem(problem, path)


if __name__ == "__main__":
    unittest.main()
