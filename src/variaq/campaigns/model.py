"""Generic, domain-neutral experiment campaign definitions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from variaq.errors import ValidationError
from variaq.solvers.base import solver_names

CAMPAIGN_FORMAT_VERSION = "1"
DEFAULT_MAX_RUNS = 500


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class SolverOverride:
    """Solver-specific configuration inside a campaign definition."""

    seed: int | None = None
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.seed is not None:
            result["seed"] = self.seed
        if self.parameters:
            result["parameters"] = dict(self.parameters)
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SolverOverride:
        return cls(
            seed=value.get("seed"),
            parameters=dict(value.get("parameters", {})),
        )


@dataclass(frozen=True, slots=True)
class ExperimentCampaign:
    """A reproducible, serializable request for a set of experiments.

    Fields are intentionally generic. Family-specific generator parameters live
    in ``generator_parameters`` so the campaign model does not hardcode MaxCut
    fields.
    """

    name: str
    family: str
    problem_sizes: tuple[int, ...]
    problem_seeds: tuple[int, ...]
    solvers: tuple[str, ...]
    repeats: int = 1
    base_seed: int = 0
    solver_config: dict[str, SolverOverride] = field(default_factory=dict)
    generator_parameters: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    notes: str = ""
    created_at: str = field(default_factory=utc_now)
    campaign_format_version: str = CAMPAIGN_FORMAT_VERSION

    def __post_init__(self) -> None:
        if not self.name:
            raise ValidationError("Campaign name cannot be empty")
        if not self.family:
            raise ValidationError("Campaign family cannot be empty")
        if not self.problem_sizes:
            raise ValidationError("Campaign problem_sizes cannot be empty")
        if not self.problem_seeds:
            raise ValidationError("Campaign problem_seeds cannot be empty")
        if not self.solvers:
            raise ValidationError("Campaign solvers cannot be empty")
        if self.repeats < 1:
            raise ValidationError("Campaign repeats must be positive")
        if any(size < 1 for size in self.problem_sizes):
            raise ValidationError("Problem sizes must be positive")
        unknown = set(self.solvers) - set(solver_names())
        if unknown:
            raise ValidationError(f"Campaign references unknown solvers: {sorted(unknown)}")
        unsupported = set(self.solver_config) - set(self.solvers)
        if unsupported:
            names = ", ".join(sorted(unsupported))
            raise ValidationError(
                f"Campaign solver_config contains solvers not in solvers list: {names}"
            )

    @property
    def requested_runs(self) -> int:
        return len(self.problem_sizes) * len(self.problem_seeds) * len(self.solvers) * self.repeats

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_format_version": self.campaign_format_version,
            "name": self.name,
            "family": self.family,
            "problem_sizes": list(self.problem_sizes),
            "problem_seeds": list(self.problem_seeds),
            "solvers": list(self.solvers),
            "repeats": self.repeats,
            "base_seed": self.base_seed,
            "solver_config": {
                name: override.to_dict() for name, override in sorted(self.solver_config.items())
            },
            "generator_parameters": dict(self.generator_parameters),
            "tags": list(self.tags),
            "notes": self.notes,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ExperimentCampaign:
        if value.get("campaign_format_version") != CAMPAIGN_FORMAT_VERSION:
            raise ValidationError(
                f"Unsupported campaign format version: {value.get('campaign_format_version')}"
            )
        config_raw = dict(value.get("solver_config", {}))
        solver_config = {
            name: SolverOverride.from_dict(override)
            if isinstance(override, dict)
            else SolverOverride()
            for name, override in config_raw.items()
        }
        return cls(
            name=str(value["name"]),
            family=str(value["family"]),
            problem_sizes=tuple(int(s) for s in value["problem_sizes"]),
            problem_seeds=tuple(int(s) for s in value["problem_seeds"]),
            solvers=tuple(str(s) for s in value["solvers"]),
            repeats=int(value.get("repeats", 1)),
            base_seed=int(value.get("base_seed", 0)),
            solver_config=solver_config,
            generator_parameters=dict(value.get("generator_parameters", {})),
            tags=tuple(str(t) for t in value.get("tags", [])),
            notes=str(value.get("notes", "")),
            created_at=str(value.get("created_at", utc_now())),
            campaign_format_version=CAMPAIGN_FORMAT_VERSION,
        )


def campaign_definition_id(campaign: ExperimentCampaign) -> str:
    """Deterministic campaign ID from canonical campaign definition content."""
    canonical = campaign.to_dict()
    canonical.pop("created_at", None)
    encoded = json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode()
    digest = hashlib.sha256(encoded).hexdigest()[:16]
    return f"campaign-{digest}"
