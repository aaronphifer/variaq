"""Bounded local campaign runner that delegates to ExperimentRunner."""

from __future__ import annotations

from typing import Any

from variaq.campaigns.model import DEFAULT_MAX_RUNS, ExperimentCampaign
from variaq.campaigns.store import CampaignStore
from variaq.errors import ValidationError
from variaq.experiments.runner import ExperimentRunner
from variaq.models import ExperimentRun, SolverConfig
from variaq.problems.assignment import AssignmentProblem
from variaq.problems.base import ProblemInstance, save_problem
from variaq.problems.graph_partition import GraphPartitionProblem
from variaq.problems.maxcut import MaxCutProblem
from variaq.problems.subset_selection import SubsetSelectionProblem
from variaq.solvers.base import get_solver


def _generate_problem(family: str, size: int, seed: int, params: dict[str, Any]) -> ProblemInstance:
    if family == "maxcut":
        edge_probability = float(params.get("edge_probability", 0.4))
        return MaxCutProblem.generate(size, edge_probability, seed)
    if family == "assignment":
        task_count = size
        resource_count = int(params.get("resource_count", size))
        prohibited_probability = float(params.get("prohibited_probability", 0.0))
        capacity = params.get("capacity")
        demand = int(params.get("demand", 1))
        return AssignmentProblem.generate(
            task_count,
            resource_count,
            seed,
            prohibited_probability=prohibited_probability,
            capacity=capacity,
            demand=demand,
        )
    if family == "subset-selection":
        candidate_count = size
        interaction_probability = float(params.get("interaction_probability", 0.0))
        budget = params.get("budget")
        min_cardinality = params.get("min_cardinality")
        max_cardinality = params.get("max_cardinality")
        return SubsetSelectionProblem.generate(
            candidate_count,
            seed,
            budget=budget,
            min_cardinality=min_cardinality,
            max_cardinality=max_cardinality,
            interaction_probability=interaction_probability,
        )
    if family == "graph-partition":
        node_count = size
        edge_probability = float(params.get("edge_probability", 0.4))
        partition_count = int(params.get("partition_count", 2))
        return GraphPartitionProblem.generate(node_count, edge_probability, partition_count, seed)
    raise ValidationError(f"Campaign runner does not support family {family!r}")


class CampaignRunner:
    """Execute a campaign definition using the normal experiment runner."""

    def __init__(
        self,
        runner: ExperimentRunner,
        store: CampaignStore,
        problems_dir: Any,
        max_runs: int = DEFAULT_MAX_RUNS,
    ) -> None:
        self.runner = runner
        self.store = store
        self.problems_dir = problems_dir
        if max_runs < 1:
            raise ValidationError("max_runs must be a positive integer")
        self.max_runs = max_runs

    def run(
        self, campaign: ExperimentCampaign, *, override_max_runs: bool = False
    ) -> dict[str, Any]:
        requested = campaign.requested_runs
        if requested > self.max_runs and not override_max_runs:
            raise ValidationError(
                f"Campaign requests {requested} runs, exceeding maximum {self.max_runs}. "
                "Use --override-max-runs to execute."
            )
        if requested < 1:
            raise ValidationError("Campaign requests zero runs")

        campaign_id = self.store.save_campaign(campaign)
        solver_instances = {name: get_solver(name) for name in campaign.solvers}

        generated_problems: dict[tuple[int, int], ProblemInstance] = {}
        all_runs: list[ExperimentRun] = []
        summary_statuses: dict[str, int] = {
            "success": 0,
            "failed": 0,
            "unavailable": 0,
            "skipped": 0,
        }

        for size in campaign.problem_sizes:
            for seed in campaign.problem_seeds:
                key = (size, seed)
                if key not in generated_problems:
                    generated_problems[key] = _generate_problem(
                        campaign.family, size, seed, campaign.generator_parameters
                    )
                problem = generated_problems[key]
                save_problem(problem, self.problems_dir / f"{problem.problem_id}.json")

                configs: dict[str, SolverConfig] = {}
                for solver_name, solver in solver_instances.items():
                    if campaign.family not in solver.supported_families:
                        summary_statuses["skipped"] += campaign.repeats
                        continue
                    override = campaign.solver_config.get(solver_name, None)
                    base_seed = (
                        override.seed
                        if override and override.seed is not None
                        else campaign.base_seed
                    )
                    parameters = dict(override.parameters) if override else {}
                    configs[solver_name] = SolverConfig(seed=base_seed, parameters=parameters)

                if not configs:
                    summary_statuses["skipped"] += campaign.repeats * len(solver_instances)
                    continue

                try:
                    runs = self.runner.benchmark(
                        problem,
                        list(solver_instances.values()),
                        configs,
                        repeats=campaign.repeats,
                    )
                except Exception:
                    # If the whole benchmark matrix fails, record one failure per requested run
                    # and continue to the next problem instance.
                    for _solver_name in configs:
                        for _ in range(campaign.repeats):
                            summary_statuses["failed"] += 1
                            # No run ID exists; store association is impossible.
                    continue

                for run in runs:
                    all_runs.append(run)
                    status = run.result.status.value
                    summary_statuses[status] = summary_statuses.get(status, 0) + 1
                    self.store.record_run(
                        campaign_id=campaign_id,
                        run_id=run.run_id,
                        status=status,
                        solver_name=run.result.solver_name,
                        problem_id=run.result.problem_id,
                        created_at=run.created_at,
                    )

        return {
            "campaign_id": campaign_id,
            "name": campaign.name,
            "family": campaign.family,
            "requested_runs": requested,
            "completed_runs": len(all_runs),
            "status_summary": summary_statuses,
            "problem_ids": sorted({run.result.problem_id for run in all_runs}),
            "run_ids": [run.run_id for run in all_runs],
        }
