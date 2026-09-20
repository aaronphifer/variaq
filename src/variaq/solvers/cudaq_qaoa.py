from __future__ import annotations

import shutil
import subprocess
import warnings
from contextlib import contextmanager
from importlib import metadata
from time import perf_counter
from typing import Any

from variaq.errors import (
    BackendUnavailableError,
    MissingOptionalDependency,
    SolverLimitError,
    ValidationError,
)
from variaq.models import BackendMetadata, SolverConfig, SolveResult, SolveStatus, utc_now
from variaq.problems.base import ProblemInstance
from variaq.problems.maxcut import MaxCutProblem
from variaq.solvers.base import Solver
from variaq.solvers.qaoa_shared import (
    candidate_parameter_digest,
    canonical_solution_from_cudaq_bitstring,
    common_qaoa_parameters,
    estimate_statevector_bytes,
    resolve_parameter_candidates,
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
    """CUDA-Q adapter implementing VariaQ's exact QAOA unitary conventions."""

    def __init__(self, cudaq: Any, problem: MaxCutProblem, p: int, seed: int) -> None:
        self.cudaq = cudaq
        self.problem = problem
        self.p = p
        self.backend_seed = seed if seed != 0 else 1
        self.kernel, parameters = cudaq.make_kernel(list)
        qubits = self.kernel.qalloc(problem.variable_count)
        self.kernel.h(qubits)
        for layer in range(p):
            for edge in problem.edges:
                # CX-RZ(theta)-CX implements RZZ(theta). Matching Qiskit uses
                # theta=-gamma*w, hence exp(+i gamma*w*ZZ/2), equivalent to
                # exp(-i gamma*C) after dropping only a global identity phase.
                self.kernel.cx(qubits[edge.u], qubits[edge.v])
                self.kernel.rz(-parameters[layer] * edge.weight, qubits[edge.v])
                self.kernel.cx(qubits[edge.u], qubits[edge.v])
            for qubit in range(problem.variable_count):
                self.kernel.rx(2.0 * parameters[p + layer], qubits[qubit])

        self.objective_constant = sum(edge.weight * 0.5 for edge in problem.edges)
        if problem.edges:
            hamiltonian = None
            for edge in problem.edges:
                term = -0.5 * edge.weight * cudaq.spin.z(edge.u) * cudaq.spin.z(edge.v)
                hamiltonian = term if hamiltonian is None else hamiltonian + term
            self.hamiltonian = hamiltonian
        else:
            self.hamiltonian = 0.0 * cudaq.spin.z(0)

    def expectation(self, parameters: tuple[float, ...]) -> float:
        result = self.cudaq.observe(self.kernel, self.hamiltonian, list(parameters))
        return float(result.expectation()) + self.objective_constant

    def sample(self, parameters: tuple[float, ...], shots: int) -> dict[tuple[int, ...], int]:
        self.cudaq.set_random_seed(self.backend_seed)
        result = self.cudaq.sample(self.kernel, list(parameters), shots_count=shots)
        counts: dict[tuple[int, ...], int] = {}
        for bitstring, count in result.items():
            solution = canonical_solution_from_cudaq_bitstring(
                str(bitstring), self.problem.variable_count
            )
            counts[solution] = counts.get(solution, 0) + int(count)
        return counts

    def logical_operation_counts(self) -> dict[str, int]:
        return {
            "h": self.problem.variable_count,
            "cx": 2 * len(self.problem.edges) * self.p,
            "rz": len(self.problem.edges) * self.p,
            "rx": self.problem.variable_count * self.p,
        }


class _CudaQQAOASolver(Solver):
    version = "1"
    supported_families = frozenset({"maxcut"})
    max_variables = 16
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
        if not isinstance(problem, MaxCutProblem):
            raise ValidationError("The CUDA-Q QAOA solvers support MaxCut only")
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
        if problem.variable_count > self.max_variables:
            raise SolverLimitError(
                f"CUDA-Q statevector QAOA is limited to {self.max_variables} variables"
            )
        precision, target_name = self._precision_and_target(config.parameters)
        estimated_bytes = estimate_statevector_bytes(problem.variable_count, precision)
        memory_guard = int(config.parameters.get("max_statevector_bytes", 2 * 1024**3))
        if memory_guard < 1:
            raise ValidationError("max_statevector_bytes must be positive")
        if estimated_bytes > memory_guard:
            raise SolverLimitError(
                f"Estimated statevector size {estimated_bytes} bytes exceeds configured "
                f"guard {memory_guard} bytes"
            )

        p, optimizer_trials, shots, warmup = common_qaoa_parameters(config.parameters)
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

        candidates = resolve_parameter_candidates(
            config.parameters, p, optimizer_trials, config.seed
        )

        with _selected_target(cudaq, target_name):
            backend = CudaQStatevectorBackend(cudaq, problem, p, config.seed)
            initialization_seconds = perf_counter() - initialization_started
            outcome = run_shared_parameter_search(
                problem,
                candidates,
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
            "candidate_parameters": [list(candidate) for candidate in candidates],
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
            "qubit_count": problem.variable_count,
            "estimated_statevector_bytes": estimated_bytes,
            "statevector_memory_guard_bytes": memory_guard,
            "parameter_order": "gammas_then_betas",
            "candidate_parameter_digest": candidate_parameter_digest(candidates),
            "candidate_expectations": list(outcome.candidate_expectations),
            "best_parameter_index": outcome.best_parameter_index,
            "best_parameters": list(outcome.best_parameters),
            "optimized_expected_objective": outcome.best_expectation,
            "sampled_unique_states": len(outcome.sample_counts),
            "logical_operation_counts": operation_counts,
            "logical_gate_count": sum(operation_counts.values()),
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
            solution=outcome.best_solution,
            objective=outcome.evaluation.objective,
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
            status=SolveStatus.SUCCESS,
        )


class CudaQQAOACpuSolver(_CudaQQAOASolver):
    name = "cudaq-cpu"
    target_kind = "cpu"


class CudaQQAOAGpuSolver(_CudaQQAOASolver):
    name = "cudaq-gpu"
    target_kind = "gpu"
