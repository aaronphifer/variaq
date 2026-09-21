"""Bounded request/response schemas for the VariaQ local web API.

Write endpoints accept only these validated shapes — no raw arbitrary JSON
reaches the campaign or analysis layers without passing through the same
``ExperimentCampaign`` / ``AnalysisQuery`` validation the CLI uses.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from variaq.campaigns.model import CAMPAIGN_FORMAT_VERSION, DEFAULT_MAX_RUNS

ALLOWED_COMPARISONS = {"classical_vs_quantum", "qiskit_vs_cudaq", "gpu_vs_cpu"}


class CampaignDefinitionIn(BaseModel):
    """A campaign definition submitted by the UI planning form."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    family: str = Field(min_length=1, max_length=64)
    problem_sizes: list[int] = Field(min_length=1, max_length=50)
    problem_seeds: list[int] = Field(min_length=1, max_length=50)
    solvers: list[str] = Field(min_length=1, max_length=20)
    repeats: int = Field(default=1, ge=1, le=100)
    base_seed: int = Field(default=0)
    generator_parameters: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=4000)
    campaign_format_version: str = CAMPAIGN_FORMAT_VERSION

    @field_validator("problem_sizes")
    @classmethod
    def sizes_positive(cls, value: list[int]) -> list[int]:
        if any(v < 1 for v in value):
            raise ValueError("problem_sizes must be positive integers")
        return value

    def to_definition(self) -> dict[str, Any]:
        return {
            "campaign_format_version": CAMPAIGN_FORMAT_VERSION,
            "name": self.name,
            "family": self.family,
            "problem_sizes": list(self.problem_sizes),
            "problem_seeds": list(self.problem_seeds),
            "solvers": list(self.solvers),
            "repeats": self.repeats,
            "base_seed": self.base_seed,
            "generator_parameters": dict(self.generator_parameters),
            "tags": list(self.tags),
            "notes": self.notes,
        }


class CampaignPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: CampaignDefinitionIn


class CampaignRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: CampaignDefinitionIn
    override_max_runs: bool = False
    max_runs: int = Field(default=DEFAULT_MAX_RUNS, ge=1, le=100000)


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: str | None = Field(default=None, max_length=128)
    run_ids: list[str] | None = Field(default=None, max_length=5000)
    group_by: list[str] = Field(default_factory=list, max_length=8)
    filters: dict[str, Any] = Field(default_factory=dict)
    scaling_x: str = Field(default="problem_size", max_length=64)
    include_failed: bool = False
    include_unavailable: bool = False
    comparisons: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("comparisons")
    @classmethod
    def comparisons_known(cls, value: list[str]) -> list[str]:
        unknown = set(value) - ALLOWED_COMPARISONS
        if unknown:
            raise ValueError(f"Unknown comparisons: {sorted(unknown)}")
        return value


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    formats: list[Literal["json", "csv", "markdown"]] | None = None
    group_by: list[str] = Field(default_factory=list, max_length=8)
    scaling_x: str = Field(default="problem_size", max_length=64)
    comparisons: list[str] = Field(default_factory=list, max_length=4)
    plots: bool = False
    overwrite: bool = False

    @field_validator("comparisons")
    @classmethod
    def comparisons_known(cls, value: list[str]) -> list[str]:
        unknown = set(value) - ALLOWED_COMPARISONS
        if unknown:
            raise ValueError(f"Unknown comparisons: {sorted(unknown)}")
        return value
