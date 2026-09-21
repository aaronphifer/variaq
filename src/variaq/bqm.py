"""Authoritative Binary Quadratic Model for VariaQ's generic QAOA path.

The BQM is a backend-neutral solver artifact. The original VariaQ problem
remains authoritative for decoding, feasibility, objective evaluation, and
constraint violations.

BQM convention
==============

The BQM represents an objective over binary variables x_i ∈ {0, 1}:

    E(x) = offset
           + Σ_i linear[i] * x_i
           + Σ_{i < j} quadratic[i, j] * x_i * x_j

The BQM objective is **always optimized in the direction of the source
problem sense**. For a ``maximize`` problem, higher BQM energy is better; for a
``minimize`` problem, lower BQM energy is better. This convention preserves
VariaQ's established MaxCut QAOA numeric behavior: the QAOA expectation for a
MaxCut instance is the expected cut weight.

For unconstrained problems the BQM energy equals the source objective. For
constrained problems, penalty terms are added with a sign that makes infeasible
assignments worse than any feasible assignment. For a maximization problem this
means penalties are subtracted (so they reduce energy when violated); for a
minimization problem penalties are added (so they increase energy when
violated).

Quadratic terms are stored with a canonical ordered pair key (i, j) where
i < j lexicographically. Self-interaction terms (i, i) are rejected during
validation; diagonal effects must be folded into ``linear``.

The ``offset`` is preserved exactly and participates in expectation values.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from variaq.errors import ValidationError
from variaq.models import OptimizationSense


@dataclass(frozen=True, slots=True)
class BinaryQuadraticModel:
    """Canonical backend-neutral QUBO representation.

    Fields:
        variable_ids: ordered tuple of binary variable identifiers. The index in
            this tuple is the canonical bit position used by QAOA backends.
        linear: linear coefficient for each variable_id.
        quadratic: quadratic coefficients keyed by canonical ordered pairs of
            distinct variable_ids.
        offset: constant term included in the BQM energy.
        sense: optimization sense of the source problem (preserved for metadata).
        source_family: source problem family name.
        source_problem_id: deterministic source problem identifier.
        penalty_metadata: structured information about constraint penalties,
            including explicit penalty values and their derivations.
        decode: per-variable metadata mapping the binary variable back to its
            semantic role in the source problem.
    """

    variable_ids: tuple[str, ...]
    linear: dict[str, float]
    quadratic: dict[tuple[str, str], float]
    offset: float
    sense: OptimizationSense
    source_family: str
    source_problem_id: str
    penalty_metadata: dict[str, Any]
    decode: tuple[dict[str, Any], ...]

    def __post_init__(self) -> None:
        # Run a lightweight validation on construction. Full validation is available
        # through validate_bqm() for callers that want explicit error messages.
        validate_bqm(self, raise_on_invalid=True)

    def energy(self, state: Mapping[str, int]) -> float:
        """Evaluate the BQM objective for a complete binary assignment.

        The state must assign every variable_id a value of 0 or 1.
        """
        if set(state.keys()) != set(self.variable_ids):
            raise ValidationError(
                f"State variables {sorted(state.keys())} do not match model variables "
                f"{sorted(self.variable_ids)}"
            )
        objective = float(self.offset)
        for var_id, value in state.items():
            if value not in (0, 1):
                raise ValidationError(f"Variable {var_id!r} has non-binary value {value!r}")
            objective += self.linear.get(var_id, 0.0) * value
        for (i, j), coeff in self.quadratic.items():
            objective += coeff * state[i] * state[j]
        return objective

    def energy_from_bits(self, bits: tuple[int, ...] | list[int]) -> float:
        """Evaluate the BQM objective using the canonical variable ordering."""
        if len(bits) != len(self.variable_ids):
            raise ValidationError(
                f"Bit vector length {len(bits)} does not match variable count "
                f"{len(self.variable_ids)}"
            )
        return self.energy(
            {var_id: int(bits[index]) for index, var_id in enumerate(self.variable_ids)}
        )

    def decode_bits(self, bits: tuple[int, ...] | list[int]) -> tuple[int, ...]:
        """Return the canonical problem solution tuple from a BQM bit vector.

        For VariaQ's current problem families the canonical binary encoding of
        the source problem matches the BQM variable ordering, so this is the
        identity mapping. The method exists so that future encodings can remap
        bits without changing solver code.
        """
        if len(bits) != len(self.variable_ids):
            raise ValidationError(
                f"Bit vector length {len(bits)} does not match variable count "
                f"{len(self.variable_ids)}"
            )
        return tuple(int(bit) for bit in bits)

    def to_dict(self) -> dict[str, Any]:
        return {
            "variable_ids": list(self.variable_ids),
            "linear": {k: v for k, v in self.linear.items()},
            "quadratic": [
                {"i": i, "j": j, "coefficient": value}
                for (i, j), value in sorted(self.quadratic.items())
            ],
            "offset": self.offset,
            "sense": self.sense.value,
            "source_family": self.source_family,
            "source_problem_id": self.source_problem_id,
            "penalty_metadata": self.penalty_metadata,
            "decode": list(self.decode),
        }

    def digest(self) -> str:
        """Return a stable SHA-256 digest of the BQM content."""
        canonical = self.to_dict()
        canonical.pop("decode", None)
        canonical.pop("penalty_metadata", None)
        canonical["linear"] = {k: float(v).hex() for k, v in sorted(canonical["linear"].items())}
        canonical["quadratic"] = [
            {"i": i, "j": j, "coefficient": float(value).hex()}
            for (i, j), value in sorted(self.quadratic.items())
        ]
        canonical["offset"] = float(canonical["offset"]).hex()
        encoded = json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()


def validate_bqm(model: BinaryQuadraticModel, *, raise_on_invalid: bool = True) -> list[str]:
    """Validate a BQM and return a list of violation messages.

    Checks:
      * duplicate variable identifiers
      * quadratic self-interaction terms
      * unknown variable references in linear or quadratic terms
      * non-finite coefficients
      * decode entries that do not match the variable list
      * missing source metadata
    """
    violations: list[str] = []

    if len(set(model.variable_ids)) != len(model.variable_ids):
        violations.append(f"Duplicate variable identifiers: {sorted(model.variable_ids)}")

    for var_id in model.linear:
        if var_id not in set(model.variable_ids):
            violations.append(f"Linear term references unknown variable {var_id!r}")
        if not math.isfinite(model.linear[var_id]):
            violations.append(f"Linear coefficient for {var_id!r} is non-finite")

    for (i, j), coeff in model.quadratic.items():
        if i == j:
            violations.append(f"Quadratic self-term for {i!r} is not allowed")
        if i not in set(model.variable_ids) or j not in set(model.variable_ids):
            violations.append(f"Quadratic term {(i, j)!r} references unknown variable")
        if not math.isfinite(coeff):
            violations.append(f"Quadratic coefficient for {(i, j)!r} is non-finite")
        if i >= j:
            violations.append(
                f"Quadratic term {(i, j)!r} is not in canonical order (expected i < j)"
            )

    if not math.isfinite(model.offset):
        violations.append("Offset is non-finite")

    if len(model.decode) != len(model.variable_ids):
        violations.append(
            f"Decode mapping length {len(model.decode)} does not match variable count"
        )

    if not model.source_family:
        violations.append("source_family is empty")
    if not model.source_problem_id:
        violations.append("source_problem_id is empty")

    if raise_on_invalid and violations:
        raise ValidationError("Invalid BinaryQuadraticModel: " + "; ".join(violations))
    return violations


def canonicalize_pair(i: str, j: str) -> tuple[str, str]:
    """Return the canonical ordered pair (min, max)."""
    return (i, j) if i < j else (j, i)
