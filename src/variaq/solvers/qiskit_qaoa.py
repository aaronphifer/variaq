from __future__ import annotations

from importlib import metadata
from time import perf_counter
from typing import Any

from variaq.bqm import BinaryQuadraticModel
from variaq.errors import MissingOptionalDependency, ValidationError
from variaq.lower import lower_to_binary_quadratic
from variaq.models import BackendMetadata, SolverConfig, SolveResult, SolveStatus, utc_now
from variaq.problems.base import ProblemInstance
from variaq.solvers.base import Solver
from variaq.solvers.qaoa_shared import (
    build_qaoa_problem,
    common_qaoa_parameters,
    estimate_statevector_bytes,
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
        bqm: BinaryQuadraticModel,
        p: int,
        seed: int,
        np: Any,
        quantum_circuit: Any,
        statevector: Any,
    ) -> None:
        self.bqm = bqm
        self.p = p
        self.np = np
        self.quantum_circuit = quantum_circuit
        self.statevector = statevector
        self.rng = np.random.default_rng(seed)
        self.num_variables = len(bqm.variable_ids)

    def build_circuit(self, parameters: tuple[float, ...]) -> Any:
        circuit = self.quantum_circuit(self.num_variables)
        circuit.h(range(self.num_variables))
        gammas = parameters[: self.p]
        betas = parameters[self.p :]
        variable_index = {var_id: index for index, var_id in enumerate(self.bqm.variable_ids)}
        for layer in range(self.p):
            for (i_var, j_var), coeff in sorted(self.bqm.quadratic.items()):
                i = variable_index[i_var]
                j = variable_index[j_var]
                # RZZ(theta) = exp(-i theta ZZ / 2). theta = -gamma * coeff
                # implements exp(+i gamma * coeff * ZZ / 2), equal to exp(-i gamma * C)
                # up to the irrelevant identity-term global phase.
                circuit.rzz(-gammas[layer] * coeff, i, j)
            for var_index, var_id in enumerate(self.bqm.variable_ids):
                linear_coeff = self.bqm.linear.get(var_id, 0.0)
                # RZ on a single qubit gives exp(-i gamma * linear * Z / 2). The
                # constant offset is ignored because it only adds a global phase.
                if linear_coeff != 0.0:
                    circuit.rz(-gammas[layer] * linear_coeff, var_index)
            for qubit in range(self.num_variables):
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
            solution = self._solution_from_state_index(state_index)
            expectation += float(probability) * self.bqm.energy_from_bits(solution)
        return expectation

    def sample(self, parameters: tuple[float, ...], shots: int) -> dict[tuple[int, ...], int]:
        probabilities = self.probabilities(parameters)
        sampled_states = self.rng.choice(len(probabilities), size=shots, p=probabilities)
        counts: dict[tuple[int, ...], int] = {}
        for state_index in sampled_states.tolist():
            solution = self._solution_from_state_index(int(state_index))
            counts[solution] = counts.get(solution, 0) + 1
        return counts

    def _solution_from_state_index(self, state_index: int) -> tuple[int, ...]:
        return tuple((state_index >> variable) & 1 for variable in range(self.num_variables))


class QiskitQAOASolver(Solver):
    """Backend-neutral QAOA solver using Qiskit's local statevector simulator."""

    name = "qaoa"
    version = "3"
    supported_families = frozenset({"maxcut", "assignment", "subset-selection"})
    max_variables = 18
    max_statevector_bytes = 512 * 1024 * 1024

    def solve(self, problem: ProblemInstance, config: SolverConfig) -> SolveResult:
        self.check_family(problem)
        self.validate_parameters(
            config.parameters,
            {"p", "optimizer_trials", "shots", "candidate_parameters", "warmup"},
        )

        bqm = lower_to_binary_quadratic(problem)
        estimated_bytes = estimate_statevector_bytes(len(bqm.variable_ids), "fp64")
        if estimated_bytes > self.max_statevector_bytes:
            raise ValidationError(
                f"Qiskit QAOA would require a {estimated_bytes}-byte statevector; "
                f"limit is {self.max_statevector_bytes} bytes"
            )
        if len(bqm.variable_ids) > self.max_variables:
            raise ValidationError(
                f"Local statevector QAOA is limited to {self.max_variables} variables"
            )

        p, optimizer_trials, shots, warmup = common_qaoa_parameters(config.parameters)
        qaoa = build_qaoa_problem(problem, bqm, config.parameters, config.seed)

        solver_started = perf_counter()
        initialization_started = perf_counter()
        np, quantum_circuit, statevector = _load_quantum_dependencies()
        backend = QiskitStatevectorBackend(bqm, p, config.seed, np, quantum_circuit, statevector)
        initialization_seconds = perf_counter() - initialization_started

        outcome = run_shared_parameter_search(
            problem,
            qaoa,
            qaoa.candidates,
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
            "candidate_parameters": [list(candidate) for candidate in qaoa.candidates],
        }
        execution_seconds = (
            outcome.warmup_seconds
            + outcome.expectation_evaluation_seconds
            + outcome.final_sampling_seconds
        )

        backend_metrics: dict[str, Any] = {
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
            "qubit_count": qaoa.num_variables,
            "binary_variable_count": qaoa.num_variables,
            "estimated_statevector_bytes": estimate_statevector_bytes(qaoa.num_variables, "fp64"),
            "parameter_order": "gammas_then_betas",
            "candidate_parameter_digest": qaoa.candidate_digest,
            "candidate_expectations": list(outcome.candidate_expectations),
            "best_parameter_index": outcome.best_parameter_index,
            "best_parameters": list(outcome.best_parameters),
            "optimized_expected_objective": outcome.best_expectation,
            "sampled_unique_states": len(outcome.sample_counts),
            "feasible_sample_count": outcome.feasible_sample_count,
            "infeasible_sample_count": outcome.infeasible_sample_count,
            "best_solution_energy": outcome.best_solution_energy,
            "best_infeasible_energy": outcome.best_infeasible_energy,
            "backend_initialization_seconds": initialization_seconds,
            "warmup_seconds": outcome.warmup_seconds,
            "parameter_search_seconds": outcome.parameter_search_seconds,
            "expectation_evaluation_seconds": outcome.expectation_evaluation_seconds,
            "final_sampling_seconds": outcome.final_sampling_seconds,
        }

        status = SolveStatus.SUCCESS if outcome.evaluation.feasible else SolveStatus.FAILED
        if outcome.feasible_sample_count == 0:
            status = SolveStatus.FAILED

        return SolveResult(
            solver_name=self.name,
            solver_version=self.version,
            problem_id=problem.problem_id,
            problem_type=problem.problem_type,
            variable_count=problem.variable_count,
            solution=outcome.best_solution if status is SolveStatus.SUCCESS else None,
            objective=outcome.evaluation.objective if status is SolveStatus.SUCCESS else None,
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
                metrics=backend_metrics,
                reproducibility_notes=(
                    "Local ideal statevector probabilities and seeded virtual sampling; "
                    "no hardware noise or remote execution.",
                    "VariaQ canonical variable i maps to Qiskit statevector index bit i.",
                ),
            ),
            seed=config.seed,
            parameters=parameters_used,
            timestamp=utc_now(),
            status=status,
        )
