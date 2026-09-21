"""Tests for the BQM model and lowering correctness across families."""

from __future__ import annotations

import unittest

from variaq.bqm import BinaryQuadraticModel, canonicalize_pair
from variaq.errors import ValidationError
from variaq.lower import lower_to_binary_quadratic
from variaq.models import OptimizationSense
from variaq.problems.assignment import AssignmentProblem
from variaq.problems.graph_partition import GraphPartitionProblem
from variaq.problems.maxcut import MaxCutProblem
from variaq.problems.subset_selection import SubsetSelectionProblem


def _enumerate_binary(n: int):
    for state in range(1 << n):
        yield tuple((state >> i) & 1 for i in range(n))


class BQMValidationTests(unittest.TestCase):
    """Unit tests for the BQM dataclass and validation helpers."""

    def test_energy_matches_offset_linear_quadratic(self) -> None:
        model = BinaryQuadraticModel(
            variable_ids=("a", "b"),
            linear={"a": 1.0, "b": 2.0},
            quadratic={("a", "b"): 3.0},
            offset=4.0,
            sense=OptimizationSense.MINIMIZE,
            source_family="test",
            source_problem_id="test-1",
            penalty_metadata={},
            decode=({}, {}),
        )
        self.assertEqual(model.energy_from_bits((1, 0)), 5.0)
        self.assertEqual(model.energy_from_bits((0, 1)), 6.0)
        self.assertEqual(model.energy_from_bits((1, 1)), 10.0)

    def test_energy_requires_exact_variables(self) -> None:
        model = BinaryQuadraticModel(
            variable_ids=("a",),
            linear={"a": 1.0},
            quadratic={},
            offset=0.0,
            sense=OptimizationSense.MINIMIZE,
            source_family="test",
            source_problem_id="test-1",
            penalty_metadata={},
            decode=({},),
        )
        with self.assertRaises(ValidationError):
            model.energy({"b": 1})

    def test_rejects_self_interaction(self) -> None:
        with self.assertRaises(ValidationError):
            BinaryQuadraticModel(
                variable_ids=("a",),
                linear={"a": 1.0},
                quadratic={("a", "a"): 1.0},
                offset=0.0,
                sense=OptimizationSense.MINIMIZE,
                source_family="test",
                source_problem_id="test-1",
                penalty_metadata={},
                decode=({},),
            )

    def test_rejects_non_canonical_quadratic_order(self) -> None:
        with self.assertRaises(ValidationError):
            BinaryQuadraticModel(
                variable_ids=("a", "b"),
                linear={"a": 1.0, "b": 2.0},
                quadratic={("b", "a"): 1.0},
                offset=0.0,
                sense=OptimizationSense.MINIMIZE,
                source_family="test",
                source_problem_id="test-1",
                penalty_metadata={},
                decode=({}, {}),
            )

    def test_digest_is_stable_and_ignores_decode(self) -> None:
        model_a = BinaryQuadraticModel(
            variable_ids=("a", "b"),
            linear={"a": 1.0, "b": 2.0},
            quadratic={("a", "b"): 3.0},
            offset=4.0,
            sense=OptimizationSense.MINIMIZE,
            source_family="test",
            source_problem_id="test-1",
            penalty_metadata={"note": "x"},
            decode=({"note": "x"}, {"note": "y"}),
        )
        model_b = BinaryQuadraticModel(
            variable_ids=("a", "b"),
            linear={"a": 1.0, "b": 2.0},
            quadratic={("a", "b"): 3.0},
            offset=4.0,
            sense=OptimizationSense.MINIMIZE,
            source_family="test",
            source_problem_id="test-1",
            penalty_metadata={"note": "y"},
            decode=({}, {}),
        )
        self.assertEqual(model_a.digest(), model_b.digest())

    def test_to_dict_is_json_safe(self) -> None:
        model = BinaryQuadraticModel(
            variable_ids=("a",),
            linear={"a": 1.0},
            quadratic={},
            offset=0.0,
            sense=OptimizationSense.MINIMIZE,
            source_family="test",
            source_problem_id="test-1",
            penalty_metadata={},
            decode=({},),
        )
        data = model.to_dict()
        import json

        json.dumps(data)


class MaxCutLoweringTests(unittest.TestCase):
    def test_triangle_maxcut_bqm_optimum(self) -> None:
        problem = MaxCutProblem.from_edges(3, [(0, 1, 1.0), (1, 2, 1.0), (0, 2, 1.0)])
        model = lower_to_binary_quadratic(problem)
        self.assertEqual(model.source_family, "maxcut")
        energies = [model.energy_from_bits(bits) for bits in _enumerate_binary(3)]
        best_energy = max(energies)
        self.assertEqual(best_energy, 2.0)
        objectives: list[float] = [
            obj
            for obj in (
                problem.evaluate(bits).objective
                for bits in _enumerate_binary(3)
                if problem.evaluate(bits).feasible
            )
            if obj is not None
        ]
        best_objective = max(objectives)
        self.assertEqual(best_objective, 2.0)

    def test_unconstrained_energy_equals_objective(self) -> None:
        problem = MaxCutProblem.from_edges(2, [(0, 1, 2.5)])
        model = lower_to_binary_quadratic(problem)
        for bits in _enumerate_binary(2):
            self.assertAlmostEqual(
                model.energy_from_bits(bits),
                problem.evaluate(bits).objective or 0.0,
            )


class AssignmentLoweringTests(unittest.TestCase):
    def test_assignment_bqm_optimum_matches_authoritative(self) -> None:
        problem = AssignmentProblem.from_score_matrix(
            ["t1", "t2"],
            ["r1", "r2"],
            {("t1", "r1"): 5.0, ("t1", "r2"): 1.0, ("t2", "r1"): 2.0, ("t2", "r2"): 4.0},
        )
        model = lower_to_binary_quadratic(problem)
        feasible_states = [
            (model.energy_from_bits(bits), problem.evaluate(bits).objective)
            for bits in _enumerate_binary(4)
            if problem.evaluate(bits).feasible and problem.evaluate(bits).objective is not None
        ]
        best_state = max(feasible_states, key=lambda item: item[0])
        self.assertEqual(best_state[1], 9.0)
        infeasible_energies = [
            model.energy_from_bits(bits)
            for bits in _enumerate_binary(4)
            if not problem.evaluate(bits).feasible
        ]
        self.assertGreater(best_state[0], max(infeasible_energies))

    def test_assignment_bqm_penalizes_infeasible(self) -> None:
        problem = AssignmentProblem.from_score_matrix(
            ["t1", "t2"],
            ["r1", "r2"],
            {("t1", "r1"): 5.0, ("t1", "r2"): 1.0, ("t2", "r1"): 2.0, ("t2", "r2"): 4.0},
        )
        model = lower_to_binary_quadratic(problem)
        feasible_energies = [
            model.energy_from_bits(bits)
            for bits in _enumerate_binary(4)
            if problem.evaluate(bits).feasible
        ]
        infeasible_energies = [
            model.energy_from_bits(bits)
            for bits in _enumerate_binary(4)
            if not problem.evaluate(bits).feasible
        ]
        self.assertGreater(min(feasible_energies), max(infeasible_energies))

    def test_assignment_capacity_rejected_in_qubo_lower(self) -> None:
        problem = AssignmentProblem.from_score_matrix(
            ["t1", "t2"],
            ["r1", "r2"],
            {("t1", "r1"): 5.0, ("t1", "r2"): 1.0, ("t2", "r1"): 2.0, ("t2", "r2"): 4.0},
            capacity={"r1": 1, "r2": 1},
        )
        with self.assertRaisesRegex(ValidationError, "capacity constraints are not supported"):
            lower_to_binary_quadratic(problem)


class SubsetLoweringTests(unittest.TestCase):
    def test_subset_bqm_optimum_matches_authoritative(self) -> None:
        # Unconstrained subset selection: BQM energy equals source objective.
        problem = SubsetSelectionProblem.from_data(
            ["a", "b", "c"],
            {"a": 1.0, "b": 2.0, "c": 3.0},
        )
        model = lower_to_binary_quadratic(problem)
        self.assertEqual(model.penalty_metadata["constraint_penalties"]["budget"], None)
        best_bits = max(
            _enumerate_binary(3),
            key=lambda bits: model.energy_from_bits(bits),
        )
        self.assertEqual(model.energy_from_bits(best_bits), 6.0)
        self.assertEqual(problem.evaluate(best_bits).objective, 6.0)

    def test_subset_bqm_respects_minimize_sense(self) -> None:
        problem = SubsetSelectionProblem.from_data(
            ["a", "b"],
            {"a": 10.0, "b": 1.0},
            sense=OptimizationSense.MINIMIZE,
        )
        model = lower_to_binary_quadratic(problem)
        feasible_states = [
            (model.energy_from_bits(bits), problem.evaluate(bits).objective)
            for bits in _enumerate_binary(2)
            if problem.evaluate(bits).feasible and problem.evaluate(bits).objective is not None
        ]
        best_feasible = min(feasible_states, key=lambda item: item[0])
        self.assertEqual(best_feasible[1], 0.0)
        feasible_energies = [e for e, _ in feasible_states]
        infeasible_energies = [
            model.energy_from_bits(bits)
            for bits in _enumerate_binary(2)
            if not problem.evaluate(bits).feasible
        ]
        if infeasible_energies:
            self.assertLess(max(feasible_energies), min(infeasible_energies))

    def test_subset_bqm_rejects_budget(self) -> None:
        problem = SubsetSelectionProblem.from_data(
            ["a", "b"],
            {"a": 1.0, "b": 1.0},
            budget=1.0,
            cost={"a": 1.0, "b": 1.0},
        )
        with self.assertRaisesRegex(ValidationError, "budget constraints are not supported"):
            lower_to_binary_quadratic(problem)

    def test_subset_bqm_rejects_cardinality(self) -> None:
        problem = SubsetSelectionProblem.from_data(
            ["a", "b"],
            {"a": 1.0, "b": 1.0},
            max_cardinality=1,
        )
        with self.assertRaisesRegex(ValidationError, "cardinality constraints are not supported"):
            lower_to_binary_quadratic(problem)

    def test_subset_lower_respects_interactions(self) -> None:
        problem = SubsetSelectionProblem.from_data(
            ["a", "b"],
            {"a": 1.0, "b": 1.0},
            interaction={frozenset({"a", "b"}): 10.0},
        )
        lower_to_binary_quadratic(problem)
        best = None
        best_score = float("-inf")
        for state in _enumerate_binary(2):
            evaluation = problem.evaluate(state)
            if evaluation.feasible and evaluation.objective is not None:
                if evaluation.objective > best_score:
                    best_score = evaluation.objective
                    best = state
        assert best is not None
        self.assertEqual(set(problem.candidate_ids), {"a", "b"})
        self.assertEqual(best_score, 12.0)


class GraphPartitionLoweringTests(unittest.TestCase):
    def test_square_partition_bqm_optimum_matches_authoritative(self) -> None:
        problem = GraphPartitionProblem.from_edges(
            ["a", "b", "c", "d"],
            [
                ("a", "b", 1.0),
                ("b", "c", 1.0),
                ("c", "d", 1.0),
                ("d", "a", 1.0),
            ],
            2,
        )
        model = lower_to_binary_quadratic(problem)
        feasible_states = [
            (model.energy_from_bits(bits), problem.evaluate(bits).objective)
            for bits in _enumerate_binary(8)
            if problem.evaluate(bits).feasible and problem.evaluate(bits).objective is not None
        ]
        best_feasible = min(feasible_states, key=lambda item: item[0])
        self.assertEqual(best_feasible[1], 0.0)
        infeasible_energies = [
            model.energy_from_bits(bits)
            for bits in _enumerate_binary(8)
            if not problem.evaluate(bits).feasible
        ]
        if infeasible_energies:
            self.assertLess(best_feasible[0], min(infeasible_energies))

    def test_graph_partition_penalizes_unassigned(self) -> None:
        problem = GraphPartitionProblem.from_edges(
            ["a", "b", "c"],
            [("a", "b", 1.0), ("b", "c", 1.0)],
            2,
        )
        model = lower_to_binary_quadratic(problem)
        feasible_energies = [
            model.energy_from_bits(bits)
            for bits in _enumerate_binary(6)
            if problem.evaluate(bits).feasible
        ]
        infeasible_energies = [
            model.energy_from_bits(bits)
            for bits in _enumerate_binary(6)
            if not problem.evaluate(bits).feasible
        ]
        self.assertLess(max(feasible_energies), min(infeasible_energies))

    def test_graph_partition_balance_rejected_in_qubo_lower(self) -> None:
        problem = GraphPartitionProblem.from_edges(
            ["a", "b", "c", "d"],
            [("a", "b", 1.0), ("b", "c", 1.0), ("c", "d", 1.0), ("d", "a", 1.0)],
            2,
            min_partition_size=2,
            max_partition_size=2,
        )
        with self.assertRaisesRegex(ValidationError, "balance constraints are not supported"):
            lower_to_binary_quadratic(problem)


class BQMJsonTests(unittest.TestCase):
    def test_json_round_trip(self) -> None:
        problem = MaxCutProblem.from_edges(3, [(0, 1, 1.0), (1, 2, 1.0)])
        model = lower_to_binary_quadratic(problem)
        import json

        data = model.to_dict()
        text = json.dumps(data)
        self.assertIn("variable_ids", text)
        self.assertIn("source_family", text)


class CanonicalPairTests(unittest.TestCase):
    def test_canonicalize_pair_orders_lexicographically(self) -> None:
        self.assertEqual(canonicalize_pair("b", "a"), ("a", "b"))
        self.assertEqual(canonicalize_pair("a", "b"), ("a", "b"))


if __name__ == "__main__":
    unittest.main()
