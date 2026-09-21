"""Generic QAOA model and shared search logic for backend-neutral BQM input.

This layer consumes a :class:`variaq.bqm.BinaryQuadraticModel` and produces a
backend-agnostic QAOA problem description: number of qubits, cost Hamiltonian
coefficients, parameter convention, and candidate parameter vectors. It does
not know about domain-specific semantics such as assignment budgets or graph
partition balance.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from variaq.bqm import BinaryQuadraticModel
from variaq.errors import MissingOptionalDependency, ValidationError
from variaq.models import Evaluation, OptimizationSense
from variaq.problems.base import ProblemInstance

QAOA_SOLVER_NAMES = frozenset({"qaoa", "cudaq-cpu", "cudaq-gpu"})


def _numpy() -> Any:
    try:
        import numpy as np
    except (ImportError, ModuleNotFoundError) as exc:
        raise MissingOptionalDependency(
            "QAOA parameter search requires NumPy. Install either "
            "pip install -e '.[quantum]' or pip install -e '.[cudaq]'."
        ) from exc
    return np


def generate_parameter_candidates(
    p: int, optimizer_trials: int, seed: int
) -> tuple[tuple[float, ...], ...]:
    """Generate the v0.1-compatible seeded QAOA random-search sequence once."""
    if p < 1 or optimizer_trials < 1:
        raise ValidationError("p and optimizer_trials must be positive")
    np = _numpy()
    rng = np.random.default_rng(seed)
    candidates: list[tuple[float, ...]] = [tuple([0.5] * p + [0.25] * p)]
    candidates.extend(
        tuple(
            float(value)
            for value in np.concatenate(
                (rng.uniform(0, math.pi, p), rng.uniform(0, math.pi / 2, p))
            )
        )
        for _ in range(optimizer_trials - 1)
    )
    return tuple(candidates)


def validate_parameter_candidates(
    candidates: Sequence[Sequence[float]], p: int, optimizer_trials: int
) -> tuple[tuple[float, ...], ...]:
    if len(candidates) != optimizer_trials:
        raise ValidationError(
            f"Expected {optimizer_trials} candidate parameter vectors, got {len(candidates)}"
        )
    normalized: list[tuple[float, ...]] = []
    for index, candidate in enumerate(candidates):
        if len(candidate) != 2 * p:
            raise ValidationError(
                f"Candidate {index} has {len(candidate)} values; expected {2 * p} for p={p}"
            )
        values = tuple(float(value) for value in candidate)
        if not all(math.isfinite(value) for value in values):
            raise ValidationError(f"Candidate {index} contains a non-finite value")
        normalized.append(values)
    return tuple(normalized)


def resolve_parameter_candidates(
    parameters: Mapping[str, Any], p: int, optimizer_trials: int, seed: int
) -> tuple[tuple[float, ...], ...]:
    supplied = parameters.get("candidate_parameters")
    if supplied is None:
        return generate_parameter_candidates(p, optimizer_trials, seed)
    if not isinstance(supplied, Sequence) or isinstance(supplied, (str, bytes)):
        raise ValidationError("candidate_parameters must be a sequence of vectors")
    return validate_parameter_candidates(supplied, p, optimizer_trials)


def candidate_parameter_digest(candidates: Sequence[Sequence[float]]) -> str:
    canonical = [[float(value).hex() for value in candidate] for candidate in candidates]
    encoded = json.dumps(canonical, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def canonical_solution_from_state_index(state_index: int, variable_count: int) -> tuple[int, ...]:
    if state_index < 0:
        raise ValidationError("State index cannot be negative")
    if state_index >= 1 << variable_count:
        raise ValidationError(
            f"State index {state_index} does not fit in {variable_count} variables"
        )
    return tuple((state_index >> variable) & 1 for variable in range(variable_count))


def canonical_solution_from_cudaq_bitstring(bitstring: str, variable_count: int) -> tuple[int, ...]:
    """CUDA-Q sample strings list q0 first; preserve that as VariaQ variable 0."""
    if len(bitstring) != variable_count:
        raise ValidationError(
            f"CUDA-Q bitstring length {len(bitstring)} does not match {variable_count} variables"
        )
    if any(bit not in "01" for bit in bitstring):
        raise ValidationError(f"Invalid CUDA-Q bitstring: {bitstring!r}")
    return tuple(int(bit) for bit in bitstring)


def estimate_statevector_bytes(variable_count: int, precision: str) -> int:
    if variable_count < 0:
        raise ValidationError("Variable count cannot be negative")
    bytes_per_amplitude = {"fp32": 8, "fp64": 16}.get(precision)
    if bytes_per_amplitude is None:
        raise ValidationError("precision must be fp32 or fp64")
    return (1 << variable_count) * bytes_per_amplitude


@dataclass(frozen=True, slots=True)
class QAOAProblem:
    """Backend-agnostic QAOA problem built from a BQM.

    Fields:
        bqm: the lowered binary quadratic model (authoritative lowering artifact)
        num_variables: number of binary variables / qubits
        p: QAOA depth
        candidates: ordered tuple of candidate parameter vectors
        candidate_digest: stable digest of candidate vectors
        cost_linear: BQM linear coefficients in variable order
        cost_quadratic: BQM quadratic coefficients as a list of (i, j, coeff)
            with i < j and indices into the canonical variable ordering
        cost_offset: BQM constant offset
    """

    bqm: BinaryQuadraticModel
    num_variables: int
    p: int
    candidates: tuple[tuple[float, ...], ...]
    candidate_digest: str
    cost_linear: tuple[float, ...]
    cost_quadratic: tuple[tuple[int, int, float], ...]
    cost_offset: float


def build_qaoa_problem(
    problem: ProblemInstance,
    bqm: BinaryQuadraticModel,
    parameters: Mapping[str, Any],
    seed: int,
) -> QAOAProblem:
    """Create a backend-agnostic QAOA problem from a lowered BQM."""
    p, optimizer_trials, shots, warmup = common_qaoa_parameters(parameters)
    candidates = resolve_parameter_candidates(parameters, p, optimizer_trials, seed)
    variable_index = {var_id: index for index, var_id in enumerate(bqm.variable_ids)}
    cost_linear = tuple(bqm.linear.get(var_id, 0.0) for var_id in bqm.variable_ids)
    cost_quadratic = tuple(
        (variable_index[i], variable_index[j], coeff)
        for (i, j), coeff in sorted(bqm.quadratic.items())
    )
    return QAOAProblem(
        bqm=bqm,
        num_variables=len(bqm.variable_ids),
        p=p,
        candidates=candidates,
        candidate_digest=candidate_parameter_digest(candidates),
        cost_linear=cost_linear,
        cost_quadratic=cost_quadratic,
        cost_offset=bqm.offset,
    )


@dataclass(frozen=True, slots=True)
class QAOASearchOutcome:
    candidate_parameters: tuple[tuple[float, ...], ...]
    candidate_expectations: tuple[float, ...]
    best_parameter_index: int
    best_parameters: tuple[float, ...]
    best_expectation: float
    sample_counts: dict[tuple[int, ...], int]
    best_solution: tuple[int, ...]
    best_solution_energy: float | None
    evaluation: Evaluation
    feasible_sample_count: int
    infeasible_sample_count: int
    best_infeasible_solution: tuple[int, ...] | None
    best_infeasible_energy: float | None
    constraint_violations: tuple[str, ...]
    warmup_seconds: float
    parameter_search_seconds: float
    expectation_evaluation_seconds: float
    final_sampling_seconds: float


def run_shared_parameter_search(
    problem: ProblemInstance,
    qaoa: QAOAProblem,
    candidates: tuple[tuple[float, ...], ...],
    evaluate_expectation: Callable[[tuple[float, ...]], float],
    sample: Callable[[tuple[float, ...], int], Mapping[tuple[int, ...], int]],
    *,
    shots: int,
    warmup: bool,
) -> QAOASearchOutcome:
    if not candidates:
        raise ValidationError("At least one candidate parameter vector is required")
    if shots < 1:
        raise ValidationError("shots must be positive")

    warmup_seconds = 0.0
    if warmup:
        warmup_started = perf_counter()
        evaluate_expectation(candidates[0])
        warmup_seconds = perf_counter() - warmup_started

    search_started = perf_counter()
    expectation_seconds = 0.0
    expectations: list[float] = []
    for index, candidate in enumerate(candidates):
        evaluation_started = perf_counter()
        expectation = float(evaluate_expectation(candidate))
        expectation_seconds += perf_counter() - evaluation_started
        if not math.isfinite(expectation):
            raise ValidationError(
                f"Backend returned a non-finite expectation for candidate {index}"
            )
        expectations.append(expectation)
    search_seconds = perf_counter() - search_started

    if problem.sense is OptimizationSense.MAXIMIZE:
        best_index = max(range(len(expectations)), key=lambda index: (expectations[index], -index))
    else:
        best_index = min(range(len(expectations)), key=lambda index: (expectations[index], index))

    sampling_started = perf_counter()
    raw_counts = sample(candidates[best_index], shots)
    sampling_seconds = perf_counter() - sampling_started
    sample_counts = {tuple(solution): int(count) for solution, count in raw_counts.items()}
    if not sample_counts or sum(sample_counts.values()) <= 0:
        raise ValidationError("Backend returned no final samples")

    best_feasible_solution: tuple[int, ...] | None = None
    best_feasible_objective: float | None = None
    best_feasible_energy: float | None = None

    best_infeasible_solution: tuple[int, ...] | None = None
    best_infeasible_energy: float | None = None

    feasible_count = 0
    infeasible_count = 0
    violation_messages: set[str] = set()

    for solution, count in sample_counts.items():
        if count < 1:
            continue
        evaluation = problem.evaluate(qaoa.bqm.decode_bits(solution))
        energy = qaoa.bqm.energy_from_bits(solution)
        if evaluation.feasible and evaluation.objective is not None:
            feasible_count += count
            if best_feasible_objective is None or _better(
                problem.sense, evaluation.objective, best_feasible_objective
            ):
                best_feasible_objective = evaluation.objective
                best_feasible_solution = solution
                best_feasible_energy = energy
        else:
            infeasible_count += count
            if best_infeasible_energy is None or energy < best_infeasible_energy:
                best_infeasible_solution = solution
                best_infeasible_energy = energy
            for violation in evaluation.constraint_violations:
                violation_messages.add(violation)

    if best_feasible_solution is None or best_feasible_objective is None:
        # Structured partial result: no feasible sample found.
        final_evaluation = Evaluation(
            objective=None,
            feasible=False,
            constraint_violations=tuple(sorted(violation_messages)),
        )
        return QAOASearchOutcome(
            candidate_parameters=candidates,
            candidate_expectations=tuple(expectations),
            best_parameter_index=best_index,
            best_parameters=candidates[best_index],
            best_expectation=expectations[best_index],
            sample_counts=sample_counts,
            best_solution=(
                best_infeasible_solution if best_infeasible_solution is not None else tuple()
            ),
            best_solution_energy=best_infeasible_energy,
            evaluation=final_evaluation,
            feasible_sample_count=feasible_count,
            infeasible_sample_count=infeasible_count,
            best_infeasible_solution=best_infeasible_solution,
            best_infeasible_energy=best_infeasible_energy,
            constraint_violations=tuple(sorted(violation_messages)),
            warmup_seconds=warmup_seconds,
            parameter_search_seconds=search_seconds,
            expectation_evaluation_seconds=expectation_seconds,
            final_sampling_seconds=sampling_seconds,
        )

    final_evaluation = problem.evaluate(qaoa.bqm.decode_bits(best_feasible_solution))
    return QAOASearchOutcome(
        candidate_parameters=candidates,
        candidate_expectations=tuple(expectations),
        best_parameter_index=best_index,
        best_parameters=candidates[best_index],
        best_expectation=expectations[best_index],
        sample_counts=sample_counts,
        best_solution=best_feasible_solution,
        best_solution_energy=best_feasible_energy,
        evaluation=final_evaluation,
        feasible_sample_count=feasible_count,
        infeasible_sample_count=infeasible_count,
        best_infeasible_solution=best_infeasible_solution,
        best_infeasible_energy=best_infeasible_energy,
        constraint_violations=tuple(sorted(violation_messages)),
        warmup_seconds=warmup_seconds,
        parameter_search_seconds=search_seconds,
        expectation_evaluation_seconds=expectation_seconds,
        final_sampling_seconds=sampling_seconds,
    )


def _better(sense: OptimizationSense, candidate: float, best: float) -> bool:
    if sense.value == "maximize":
        return candidate > best
    return candidate < best


def common_qaoa_parameters(parameters: Mapping[str, Any]) -> tuple[int, int, int, bool]:
    p = int(parameters.get("p", 1))
    optimizer_trials = int(parameters.get("optimizer_trials", 32))
    shots = int(parameters.get("shots", 1024))
    warmup = parameters.get("warmup", False)
    if not isinstance(warmup, bool):
        raise ValidationError("warmup must be true or false")
    if p < 1 or optimizer_trials < 1 or shots < 1:
        raise ValidationError("p, optimizer_trials, and shots must be positive")
    return p, optimizer_trials, shots, warmup
