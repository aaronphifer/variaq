"""Campaign planning: predict scope, counts, and warnings without executing solvers."""

from __future__ import annotations

from typing import Any

from variaq.campaigns.model import DEFAULT_MAX_RUNS, ExperimentCampaign
from variaq.capabilities import gather_capabilities


class CampaignPlan:
    """Read-only summary of what a campaign would execute."""

    def __init__(self, campaign: ExperimentCampaign) -> None:
        self.campaign = campaign

    def build(self) -> dict[str, Any]:
        sizes = self.campaign.problem_sizes
        seeds = self.campaign.problem_seeds
        solvers = self.campaign.solvers
        repeats = self.campaign.repeats

        problem_count = len(sizes) * len(seeds)
        requested_runs = problem_count * len(solvers) * repeats

        solver_breakdown: list[dict[str, Any]] = []
        unavailable: list[dict[str, Any]] = []
        capabilities = gather_capabilities()
        solver_map = {entry["name"]: entry for entry in capabilities["solvers"]}

        estimated_qaoa_runs = 0
        max_binary_variables: int | None = None

        for solver_name in solvers:
            solver_entry = solver_map.get(solver_name, {})
            supported_families = set(solver_entry.get("supported_families", []))
            available = bool(solver_entry.get("available"))
            installed = bool(solver_entry.get("installed"))
            supported = solver_name in {
                s["name"] for s in capabilities["solvers"] if s["supported"]
            }
            runs = len(sizes) * len(seeds) * repeats

            if solver_name in {"qaoa", "cudaq-cpu", "cudaq-gpu"}:
                estimated_qaoa_runs += runs

            if self.campaign.family not in supported_families:
                unavailable.append(
                    {
                        "solver": solver_name,
                        "reason": f"Solver does not support family {self.campaign.family!r}",
                        "requested_runs": runs,
                    }
                )
            elif not available or not installed:
                reason = solver_entry.get("reason") or "Solver is not available in this environment"
                unavailable.append(
                    {
                        "solver": solver_name,
                        "reason": reason,
                        "requested_runs": runs,
                    }
                )

            solver_breakdown.append(
                {
                    "solver": solver_name,
                    "supported": supported,
                    "installed": installed,
                    "available": available,
                    "requested_runs": runs,
                }
            )

        # Estimate max binary variables from a representative largest instance without solving.
        family = self.campaign.family
        largest_size = max(sizes)
        try:
            if family == "maxcut":
                max_binary_variables = largest_size
            elif family == "assignment":
                resource_count = self.campaign.generator_parameters.get(
                    "resource_count", largest_size
                )
                max_binary_variables = largest_size * int(resource_count)
            elif family == "subset-selection":
                max_binary_variables = largest_size
            elif family == "graph-partition":
                partition_count = self.campaign.generator_parameters.get("partition_count", 2)
                max_binary_variables = largest_size * int(partition_count)
        except Exception:
            max_binary_variables = None

        warnings: list[str] = []
        if requested_runs > DEFAULT_MAX_RUNS:
            warnings.append(
                f"Campaign requests {requested_runs} runs; default maximum is {DEFAULT_MAX_RUNS}. "
                "Use --override-max-runs to execute."
            )
        exact_runs = sum(
            runs
            for entry in solver_breakdown
            if entry["solver"] == "exact" and entry["available"]
            for runs in [entry["requested_runs"]]
        )
        if exact_runs > 0:
            max_exact_states = 1 << min(max_binary_variables or 0, 63)
            warnings.append(
                f"Exact solver would enumerate up to {max_exact_states} states "
                "for the largest instance."
            )
        if (
            estimated_qaoa_runs > 0
            and not any(
                entry["solver"] == "qaoa" and entry["available"] for entry in solver_breakdown
            )
            and not any(
                entry["solver"].startswith("cudaq") and entry["available"]
                for entry in solver_breakdown
            )
        ):
            warnings.append(
                "No quantum backend appears available; QAOA runs will be recorded as unavailable."
            )

        return {
            "campaign_id": "not-yet-executed",
            "name": self.campaign.name,
            "family": family,
            "problem_instance_count": problem_count,
            "requested_runs": requested_runs,
            "repeats": repeats,
            "solver_breakdown": solver_breakdown,
            "unavailable": unavailable,
            "estimated_quantum_runs": estimated_qaoa_runs,
            "max_binary_variables": max_binary_variables,
            "default_max_runs": DEFAULT_MAX_RUNS,
            "exceeds_default_max": requested_runs > DEFAULT_MAX_RUNS,
            "warnings": warnings,
        }
