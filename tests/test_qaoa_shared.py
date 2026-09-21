import math
import unittest

from variaq.errors import ValidationError
from variaq.experiments.runner import ExperimentRunner
from variaq.models import SolverConfig, SolveResult
from variaq.problems.base import ProblemInstance
from variaq.problems.maxcut import MaxCutProblem
from variaq.solvers.base import Solver
from variaq.solvers.qaoa_shared import (
    QAOAProblem,
    candidate_parameter_digest,
    canonical_solution_from_cudaq_bitstring,
    canonical_solution_from_state_index,
    generate_parameter_candidates,
    run_shared_parameter_search,
)


class NamedTestSolver(Solver):
    version = "test"
    supported_families = frozenset({"maxcut"})

    def __init__(self, name: str) -> None:
        self.name = name

    def solve(self, problem: ProblemInstance, config: SolverConfig) -> SolveResult:
        raise NotImplementedError


class SharedQAOATests(unittest.TestCase):
    def test_seeded_candidates_are_repeatable_and_ordered(self) -> None:
        first = generate_parameter_candidates(2, 5, 42)
        second = generate_parameter_candidates(2, 5, 42)
        different = generate_parameter_candidates(2, 5, 43)
        self.assertEqual(first, second)
        self.assertNotEqual(first, different)
        self.assertEqual(first[0], (0.5, 0.5, 0.25, 0.25))
        self.assertEqual(candidate_parameter_digest(first), candidate_parameter_digest(second))

    def test_runner_injects_one_identical_candidate_sequence(self) -> None:
        from variaq.problems.maxcut import MaxCutProblem

        problem = MaxCutProblem.from_edges(2, [(0, 1)])
        solvers: list[Solver] = [NamedTestSolver("qaoa"), NamedTestSolver("cudaq-cpu")]
        configs = {
            name: SolverConfig(
                seed=42,
                parameters={"p": 2, "optimizer_trials": 5, "shots": 64},
            )
            for name in ("qaoa", "cudaq-cpu")
        }
        prepared = ExperimentRunner._matched_repeat_configs(problem, solvers, configs, repeat=0)
        qiskit_candidates = prepared["qaoa"].parameters["candidate_parameters"]
        cudaq_candidates = prepared["cudaq-cpu"].parameters["candidate_parameters"]
        self.assertEqual(qiskit_candidates, cudaq_candidates)
        self.assertIs(qiskit_candidates, cudaq_candidates)

    def test_runner_rejects_mismatched_quantum_configuration(self) -> None:
        from variaq.problems.maxcut import MaxCutProblem

        problem = MaxCutProblem.from_edges(2, [(0, 1)])
        solvers: list[Solver] = [NamedTestSolver("qaoa"), NamedTestSolver("cudaq-cpu")]
        configs = {
            "qaoa": SolverConfig(parameters={"p": 1}),
            "cudaq-cpu": SolverConfig(parameters={"p": 2}),
        }
        with self.assertRaisesRegex(ValidationError, "identical p"):
            ExperimentRunner._matched_repeat_configs(problem, solvers, configs, repeat=0)

    def test_canonical_bit_order_is_explicit_and_objectively_detectable(self) -> None:
        self.assertEqual(canonical_solution_from_state_index(1, 3), (1, 0, 0))
        self.assertEqual(canonical_solution_from_cudaq_bitstring("100", 3), (1, 0, 0))
        problem = MaxCutProblem.from_edges(3, [(0, 1, 1.0), (1, 2, 3.0)])
        canonical = problem.evaluate(canonical_solution_from_cudaq_bitstring("100", 3))
        reversed_interpretation = problem.evaluate((0, 0, 1))
        self.assertEqual(canonical.objective, 1.0)
        self.assertEqual(reversed_interpretation.objective, 3.0)

    def test_shared_search_ranks_expectations_but_uses_authoritative_evaluator(self) -> None:
        problem = MaxCutProblem.from_edges(2, [(0, 1)])
        from variaq.bqm import BinaryQuadraticModel

        bqm = BinaryQuadraticModel(
            variable_ids=("x_0", "x_1"),
            linear={"x_0": 0.0, "x_1": 0.0},
            quadratic={("x_0", "x_1"): -1.0},
            offset=0.5,
            sense=problem.sense,
            source_family="maxcut",
            source_problem_id=problem.problem_id,
            penalty_metadata={},
            decode=({}, {}),
        )
        qaoa = QAOAProblem(
            bqm=bqm,
            num_variables=2,
            p=1,
            candidates=((0.0, 0.0), (math.pi / 2, math.pi / 8)),
            candidate_digest="",
            cost_linear=(0.0, 0.0),
            cost_quadratic=((0, 1, -1.0),),
            cost_offset=0.5,
        )
        expectation_values = {qaoa.candidates[0]: 0.5, qaoa.candidates[1]: 1.0}

        outcome = run_shared_parameter_search(
            problem,
            qaoa,
            qaoa.candidates,
            expectation_values.__getitem__,
            lambda parameters, shots: {(1, 0): shots},
            shots=16,
            warmup=False,
        )
        self.assertEqual(outcome.best_parameter_index, 1)
        self.assertEqual(outcome.best_expectation, 1.0)
        self.assertEqual(outcome.evaluation.objective, 1.0)


if __name__ == "__main__":
    unittest.main()
