from __future__ import annotations

from importlib import metadata
from time import perf_counter
from typing import Any

from variaq.errors import MissingOptionalDependency, ValidationError
from variaq.models import BackendMetadata, SolverConfig, SolveResult, SolveStatus, utc_now
from variaq.problems.base import ProblemInstance
from variaq.problems.maxcut import MaxCutProblem
from variaq.solvers.base import Solver
from variaq.solvers.qaoa_shared import (
    candidate_parameter_digest,
    canonical_solution_from_state_index,
    common_qaoa_parameters,
    estimate_statevector_bytes,
    resolve_parameter_candidates,
    run_shared_parameter_search,
)


def _load_quantum_dependencies() -> tuple[Any, Any, Any]:
    try:
        import numpy as np
        from qiskit import QuantumCircuit
        from qiskit.quantum_info import Statevector
    except (ImportError, ModuleNotFoundError) as exc:
        raise MissingOptionalDependency(
            "Qiskit QAOA requires the optional quantum dependencies. "
            "Install with: pip install -e '.[quantum]'"
        ) from exc
    return np, QuantumCircuit, Statevector


class QiskitStatevectorBackend:
    """Qiskit adapter for VariaQ's canonical QAOA and variable ordering."""

    def __init__(
        self,
        problem: MaxCutProblem,
        p: int,
        seed: int,
        np: Any,
        quantum_circuit: Any,
        statevector: Any,
    ) -> None:
        self.problem = problem
        self.p = p
        self.np = np
        self.quantum_circuit = quantum_circuit
        self.statevector = statevector
        self.rng = np.random.default_rng(seed)

    def build_circuit(self, parameters: tuple[float, ...]) -> Any:
        circuit = self.quantum_circuit(self.problem.variable_count)
        circuit.h(range(self.problem.variable_count))
        gammas = parameters[: self.p]
        betas = parameters[self.p :]
        for layer in range(self.p):
            for edge in self.problem.edges:
                # RZZ(theta) = exp(-i theta ZZ / 2). theta=-gamma*w therefore
                # implements exp(+i gamma*w*ZZ/2), equal to exp(-i gamma*C)
                # up to the irrelevant MaxCut identity-term global phase.
                circuit.rzz(-gammas[layer] * edge.weight, edge.u, edge.v)
            for qubit in range(self.problem.variable_count):
                # RX(2*beta) = exp(-i beta X), the canonical QAOA mixer.
                circuit.rx(2.0 * betas[layer], qubit)
        return circuit

    def probabilities(self, parameters: tuple[float, ...]) -> Any:
        return self.statevector.from_instruction(self.build_circuit(parameters)).probabilities()

    def expectation(self, parameters: tuple[float, ...]) -> float:
        probabilities = self.probabilities(parameters)
        expectation = 0.0
        for state_index, probability in enumerate(probabilities):
            if probability <= 0:
                continue
            solution = canonical_solution_from_state_index(state_index, self.problem.variable_count)
            objective = self.problem.evaluate(solution).objective
            assert objective is not None
            expectation += float(probability) * objective
        return expectation

    def sample(self, parameters: tuple[float, ...], shots: int) -> dict[tuple[int, ...], int]:
        probabilities = self.probabilities(parameters)
        sampled_states = self.rng.choice(len(probabilities), size=shots, p=probabilities)
        counts: dict[tuple[int, ...], int] = {}
        for state_index in sampled_states.tolist():
            solution = canonical_solution_from_state_index(
                int(state_index), self.problem.variable_count
            )
            counts[solution] = counts.get(solution, 0) + 1
        return counts


class QiskitQAOASolver(Solver):
    """Matched QAOA MaxCut solver using Qiskit's local statevector only."""

    name = "qaoa"
    version = "2"
    max_variables = 16

    def solve(self, problem: ProblemInstance, config: SolverConfig) -> SolveResult:
        if not isinstance(problem, MaxCutProblem):
            raise ValidationError("The Qiskit QAOA solver supports MaxCut only")
        self.validate_parameters(
            config.parameters,
            {"p", "optimizer_trials", "shots", "candidate_parameters", "warmup"},
        )
        if problem.variable_count > self.max_variables:
            raise ValidationError(
                f"Local statevector QAOA is limited to {self.max_variables} variables"
            )

        p, optimizer_trials, shots, warmup = common_qaoa_parameters(config.parameters)
        solver_started = perf_counter()
        initialization_started = perf_counter()
        np, quantum_circuit, statevector = _load_quantum_dependencies()
        backend = QiskitStatevectorBackend(
            problem, p, config.seed, np, quantum_circuit, statevector
        )
        initialization_seconds = perf_counter() - initialization_started
        candidates = resolve_parameter_candidates(
            config.parameters, p, optimizer_trials, config.seed
        )
        outcome = run_shared_parameter_search(
            problem,
            candidates,
            backend.expectation,
            backend.sample,
            shots=shots,
            warmup=warmup,
        )
        elapsed = perf_counter() - solver_started

        best_circuit = backend.build_circuit(outcome.best_parameters)
        operation_counts = {str(key): int(value) for key, value in best_circuit.count_ops().items()}
        parameters_used = {
            "p": p,
            "optimizer": "seeded-random-search",
            "optimizer_trials": optimizer_trials,
            "shots": shots,
            "warmup": warmup,
            "parameter_order": "gammas_then_betas",
            "candidate_parameters": [list(candidate) for candidate in candidates],
        }
        execution_seconds = (
            outcome.warmup_seconds
            + outcome.expectation_evaluation_seconds
            + outcome.final_sampling_seconds
        )
        return SolveResult(
            solver_name=self.name,
            solver_version=self.version,
            problem_id=problem.problem_id,
            problem_type=problem.problem_type,
            variable_count=problem.variable_count,
            solution=outcome.best_solution,
            objective=outcome.evaluation.objective,
            feasible=outcome.evaluation.feasible,
            constraint_violations=outcome.evaluation.constraint_violations,
            wall_time_seconds=elapsed,
            solver_time_seconds=execution_seconds,
            backend=BackendMetadata(
                backend_type="quantum_simulator",
                name="qiskit.quantum_info.Statevector",
                provider="qiskit-local",
                is_local=True,
                versions={
                    "qiskit": metadata.version("qiskit"),
                    "numpy": metadata.version("numpy"),
                },
                metrics={
                    "framework": "qiskit",
                    "target_name": "qiskit.quantum_info.Statevector",
                    "target_type": "CPU simulator",
                    "floating_point_precision": "fp64",
                    "qaoa_depth_p": p,
                    "optimizer": "seeded-random-search",
                    "optimizer_trials": optimizer_trials,
                    "shots": shots,
                    "circuit_depth": best_circuit.depth(),
                    "gate_count": sum(operation_counts.values()),
                    "operation_counts": operation_counts,
                    "qubit_count": problem.variable_count,
                    "estimated_statevector_bytes": estimate_statevector_bytes(
                        problem.variable_count, "fp64"
                    ),
                    "parameter_order": "gammas_then_betas",
                    "candidate_parameter_digest": candidate_parameter_digest(candidates),
                    "candidate_expectations": list(outcome.candidate_expectations),
                    "best_parameter_index": outcome.best_parameter_index,
                    "best_parameters": list(outcome.best_parameters),
                    "optimized_expected_objective": outcome.best_expectation,
                    "sampled_unique_states": len(outcome.sample_counts),
                    "backend_initialization_seconds": initialization_seconds,
                    "warmup_seconds": outcome.warmup_seconds,
                    "parameter_search_seconds": outcome.parameter_search_seconds,
                    "expectation_evaluation_seconds": outcome.expectation_evaluation_seconds,
                    "final_sampling_seconds": outcome.final_sampling_seconds,
                },
                reproducibility_notes=(
                    "Local ideal statevector probabilities and seeded virtual sampling; "
                    "no hardware noise or remote execution.",
                    "VariaQ canonical variable i maps to Qiskit statevector index bit i.",
                ),
            ),
            seed=config.seed,
            parameters=parameters_used,
            timestamp=utc_now(),
            status=SolveStatus.SUCCESS,
        )
