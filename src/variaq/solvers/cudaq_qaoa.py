from __future__ import annotations

import shutil
import subprocess
import warnings
from contextlib import contextmanager
from importlib import metadata
from time import perf_counter
from typing import Any

from variaq.bqm import BinaryQuadraticModel
from variaq.errors import (
    BackendUnavailableError,
    MissingOptionalDependency,
    SolverLimitError,
    ValidationError,
)
from variaq.lower import lower_to_binary_quadratic
from variaq.models import BackendMetadata, SolverConfig, SolveResult, SolveStatus, utc_now
from variaq.problems.base import ProblemInstance
from variaq.solvers.base import Solver
from variaq.solvers.qaoa_shared import (
    build_qaoa_problem,
    canonical_solution_from_cudaq_bitstring,
    common_qaoa_parameters,
    estimate_statevector_bytes,
    run_shared_parameter_search,
)


def _load_cudaq() -> Any:
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="cudaq-logical is in preview.*")
            warnings.filterwarnings(
                "ignore", message="The CUDA-Q `sample` and `observe` algorithmic primitives.*"
            )
            import cudaq
    except (ImportError, ModuleNotFoundError, OSError) as exc:
        raise MissingOptionalDependency(
            "CUDA-Q QAOA requires the optional CUDA-Q dependencies. "
            "Install with: pip install -e '.[cudaq]'"
        ) from exc
    return cudaq


@contextmanager
def _selected_target(cudaq: Any, target_name: str) -> Any:
    previous = cudaq.get_target()
    cudaq.set_target(target_name)
    try:
        yield
    finally:
        cudaq.set_target(previous)


def _optional_gpu_metadata() -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return {}
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0:
        return {}
    devices = []
    for line in result.stdout.splitlines():
        values = [value.strip() for value in line.split(",")]
        if len(values) == 3:
            devices.append(
                {
                    "model": values[0],
                    "total_memory_mib": int(values[1]),
                    "driver_version": values[2],
                }
            )
    return {"gpu_count": len(devices), "gpus": devices} if devices else {}


class CudaQStatevectorBackend:
    """CUDA-Q adapter consuming a VariaQ BQM with canonical variable ordering."""

    def __init__(self, cudaq: Any, bqm: BinaryQuadraticModel, p: int, seed: int) -> None:
        self.cudaq = cudaq
        self.bqm = bqm
        self.p = p
        self.num_variables = len(bqm.variable_ids)
        self.backend_seed = seed if seed != 0 else 1
        self.kernel, parameters = cudaq.make_kernel(list)
        qubits = self.kernel.qalloc(self.num_variables)
        self.kernel.h(qubits)
        variable_index = {var_id: index for index, var_id in enumerate(bqm.variable_ids)}
        for layer in range(p):
            for (i_var, j_var), coeff in sorted(bqm.quadratic.items()):
                i = variable_index[i_var]
                j = variable_index[j_var]
                # CX-RZ(theta)-CX implements RZZ(theta). Matching Qiskit uses
                # theta = -gamma * coeff, hence exp(+i gamma * coeff * ZZ / 2).
                self.kernel.cx(qubits[i], qubits[j])
                self.kernel.rz(-parameters[layer] * coeff, qubits[j])
                self.kernel.cx(qubits[i], qubits[j])
            for var_index, var_id in enumerate(bqm.variable_ids):
                linear_coeff = bqm.linear.get(var_id, 0.0)
                if linear_coeff != 0.0:
                    self.kernel.rz(-parameters[layer] * linear_coeff, qubits[var_index])
            for qubit in range(self.num_variables):
                self.kernel.rx(2.0 * parameters[p + layer], qubits[qubit])

        if bqm.quadratic or bqm.linear:
            variable_index = {var_id: index for index, var_id in enumerate(bqm.variable_ids)}
            # Convert BQM over {0,1} to Ising over {+1,-1}: x = (1 - z)/2.
            # E = offset + Σ linear_i x_i + Σ_{i<j} q_ij x_i x_j
            #   = constant + Σ h_i z_i + Σ_{i<j} J_ij z_i z_j
            # where:
            #   J_ij = q_ij / 4
            #   h_i = -linear_i/2 - Σ_{j≠i} q_{min(i,j),max(i,j)} / 4
            #   constant = offset + Σ linear_i/2 + Σ_{i<j} q_ij/4
            constant = bqm.offset
            linear_ising: dict[str, float] = {
                var_id: -0.5 * coeff for var_id, coeff in bqm.linear.items()
            }
            quadratic_ising: dict[tuple[str, str], float] = {
                pair: 0.25 * coeff for pair, coeff in bqm.quadratic.items()
            }
            for (i_var, j_var), coeff in bqm.quadratic.items():
                constant += 0.25 * coeff
                linear_ising[i_var] -= 0.25 * coeff
                linear_ising[j_var] -= 0.25 * coeff
            for _var_id, coeff in bqm.linear.items():
                constant += 0.5 * coeff

            hamiltonian = None
            for (i_var, j_var), coeff in quadratic_ising.items():
                i = variable_index[i_var]
                j = variable_index[j_var]
                term = coeff * cudaq.spin.z(i) * cudaq.spin.z(j)
                hamiltonian = term if hamiltonian is None else hamiltonian + term
            for var_id, coeff in linear_ising.items():
                if coeff != 0.0:
                    index = variable_index[var_id]
                    term = coeff * cudaq.spin.z(index)
                    hamiltonian = term if hamiltonian is None else hamiltonian + term
            self.hamiltonian = hamiltonian if hamiltonian is not None else 0.0 * cudaq.spin.z(0)
            self.objective_constant = constant
        else:
            self.hamiltonian = 0.0 * cudaq.spin.z(0)
            self.objective_constant = bqm.offset

    def expectation(self, parameters: tuple[float, ...]) -> float:
        result = self.cudaq.observe(self.kernel, self.hamiltonian, list(parameters))
        return float(result.expectation()) + self.objective_constant

    def sample(self, parameters: tuple[float, ...], shots: int) -> dict[tuple[int, ...], int]:
        self.cudaq.set_random_seed(self.backend_seed)
        result = self.cudaq.sample(self.kernel, list(parameters), shots_count=shots)
        counts: dict[tuple[int, ...], int] = {}
        for bitstring, count in result.items():
            solution = canonical_solution_from_cudaq_bitstring(str(bitstring), self.num_variables)
            counts[solution] = counts.get(solution, 0) + int(count)
        return counts

    def logical_operation_counts(self) -> dict[str, int]:
        return {
            "h": self.num_variables,
            "cx": 2 * len(self.bqm.quadratic) * self.p,
            "rz": (len(self.bqm.quadratic) + sum(1 for v in self.bqm.linear.values() if v != 0.0))
            * self.p,
            "rx": self.num_variables * self.p,
        }


class _CudaQQAOASolver(Solver):
    version = "2"
    supported_families = frozenset({"maxcut", "assignment", "subset-selection"})
    max_variables = 18
    max_statevector_bytes = 2 * 1024**3
    target_kind: str

    def _precision_and_target(self, parameters: dict[str, Any]) -> tuple[str, str]:
        precision = str(
            parameters.get("precision", "fp64" if self.target_kind == "cpu" else "fp32")
        )
        if precision not in {"fp32", "fp64"}:
            raise ValidationError("precision must be fp32 or fp64")
        if self.target_kind == "cpu":
            if precision != "fp64":
                raise ValidationError("qpp-cpu supports VariaQ's fp64 mode only")
            return precision, "qpp-cpu"
        return precision, "nvidia" if precision == "fp32" else "nvidia-fp64"

    def solve(self, problem: ProblemInstance, config: SolverConfig) -> SolveResult:
        self.check_family(problem)
        self.validate_parameters(
            config.parameters,
            {
                "p",
                "optimizer_trials",
                "shots",
                "candidate_parameters",
                "warmup",
                "precision",
                "max_statevector_bytes",
            },
        )

        bqm = lower_to_binary_quadratic(problem)
        if len(bqm.variable_ids) > self.max_variables:
            raise SolverLimitError(
                f"CUDA-Q statevector QAOA is limited to {self.max_variables} variables"
            )

        precision, target_name = self._precision_and_target(config.parameters)
        estimated_bytes = estimate_statevector_bytes(len(bqm.variable_ids), precision)
        memory_guard = int(
            config.parameters.get("max_statevector_bytes", self.max_statevector_bytes)
        )
        if memory_guard < 1:
            raise ValidationError("max_statevector_bytes must be positive")
        if memory_guard > self.max_statevector_bytes:
            memory_guard = self.max_statevector_bytes
        if estimated_bytes > memory_guard:
            raise SolverLimitError(
                f"Estimated statevector size {estimated_bytes} bytes exceeds configured "
                f"guard {memory_guard} bytes"
            )

        p, optimizer_trials, shots, warmup = common_qaoa_parameters(config.parameters)
        qaoa = build_qaoa_problem(problem, bqm, config.parameters, config.seed)

        solver_started = perf_counter()
        initialization_started = perf_counter()
        cudaq = _load_cudaq()
        if not cudaq.has_target(target_name):
            raise BackendUnavailableError(
                f"CUDA-Q target {target_name!r} is not installed on this host",
                backend_name=target_name,
                provider="cudaq",
            )
        if self.target_kind == "gpu":
            try:
                gpu_count = int(cudaq.num_available_gpus())
            except Exception as exc:
                raise BackendUnavailableError(
                    f"CUDA-Q could not determine NVIDIA GPU availability: {exc}",
                    backend_name=target_name,
                    provider="cudaq",
                ) from exc
            if gpu_count < 1:
                raise BackendUnavailableError(
                    "CUDA-Q is installed, but no compatible NVIDIA GPU is available",
                    backend_name=target_name,
                    provider="cudaq",
                )

        with _selected_target(cudaq, target_name):
            backend = CudaQStatevectorBackend(cudaq, bqm, p, config.seed)
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
            operation_counts = backend.logical_operation_counts()
        elapsed = perf_counter() - solver_started

        parameters_used = {
            "p": p,
            "optimizer": "seeded-random-search",
            "optimizer_trials": optimizer_trials,
            "shots": shots,
            "warmup": warmup,
            "precision": precision,
            "parameter_order": "gammas_then_betas",
            "candidate_parameters": [list(candidate) for candidate in qaoa.candidates],
        }
        execution_seconds = (
            outcome.warmup_seconds
            + outcome.expectation_evaluation_seconds
            + outcome.final_sampling_seconds
        )
        metrics: dict[str, Any] = {
            "framework": "cudaq",
            "target_name": target_name,
            "target_type": f"{self.target_kind.upper()} simulator",
            "floating_point_precision": precision,
            "simulator_backend": target_name,
            "qaoa_depth_p": p,
            "optimizer": "seeded-random-search",
            "optimizer_trials": optimizer_trials,
            "shots": shots,
            "qubit_count": qaoa.num_variables,
            "binary_variable_count": qaoa.num_variables,
            "estimated_statevector_bytes": estimated_bytes,
            "statevector_memory_guard_bytes": memory_guard,
            "parameter_order": "gammas_then_betas",
            "candidate_parameter_digest": qaoa.candidate_digest,
            "candidate_expectations": list(outcome.candidate_expectations),
            "best_parameter_index": outcome.best_parameter_index,
            "best_parameters": list(outcome.best_parameters),
            "optimized_expected_objective": outcome.best_expectation,
            "sampled_unique_states": len(outcome.sample_counts),
            "logical_operation_counts": operation_counts,
            "logical_gate_count": sum(operation_counts.values()),
            "feasible_sample_count": outcome.feasible_sample_count,
            "infeasible_sample_count": outcome.infeasible_sample_count,
            "best_solution_energy": outcome.best_solution_energy,
            "best_infeasible_energy": outcome.best_infeasible_energy,
            "backend_initialization_seconds": initialization_seconds,
            "warmup_seconds": outcome.warmup_seconds,
            "parameter_search_seconds": outcome.parameter_search_seconds,
            "expectation_evaluation_seconds": outcome.expectation_evaluation_seconds,
            "final_sampling_seconds": outcome.final_sampling_seconds,
            "requested_seed": config.seed,
            "backend_sampling_seed": backend.backend_seed,
        }
        if self.target_kind == "gpu":
            metrics.update(_optional_gpu_metadata())

        status = SolveStatus.SUCCESS if outcome.evaluation.feasible else SolveStatus.FAILED
        if outcome.feasible_sample_count == 0:
            status = SolveStatus.FAILED

        notes = [
            "Local ideal CUDA-Q simulation using cudaq.observe for expectations and "
            "cudaq.sample for final samples; no QPU execution.",
            "CUDA-Q sample strings are normalized from q0-first order to VariaQ variable order.",
        ]
        if config.seed == 0:
            notes.append("CUDA-Q treats seed 0 as unseeded; VariaQ maps it to backend seed 1.")

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
                backend_type=f"quantum_simulator_{self.target_kind}",
                name=target_name,
                provider="cudaq",
                is_local=True,
                versions={"cudaq": metadata.version("cudaq")},
                metrics=metrics,
                reproducibility_notes=tuple(notes),
            ),
            seed=config.seed,
            parameters=parameters_used,
            timestamp=utc_now(),
            status=status,
        )


class CudaQQAOACpuSolver(_CudaQQAOASolver):
    name = "cudaq-cpu"
    target_kind = "cpu"


class CudaQQAOAGpuSolver(_CudaQQAOASolver):
    name = "cudaq-gpu"
    target_kind = "gpu"
