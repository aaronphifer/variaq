"""Bounded local campaign runner that delegates to ExperimentRunner."""

from __future__ import annotations

from typing import Any

from variaq.campaigns.model import DEFAULT_MAX_RUNS, ExperimentCampaign
from variaq.campaigns.store import CampaignStore
from variaq.errors import ValidationError
from variaq.experiments.runner import ExperimentRunner
from variaq.models import ExperimentRun, SolverConfig
from variaq.problems.assignment import AssignmentProblem
from variaq.problems.base import ProblemInstance, load_problem, save_problem
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
        self,
        campaign: ExperimentCampaign,
        *,
        override_max_runs: bool = False,
        on_run_recorded: Any | None = None,
        should_abort: Any | None = None,
        web_task_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a campaign sequentially.

        ``on_run_recorded`` (optional) is invoked after each run is persisted and
        associated with the campaign; ``should_abort`` (optional) is polled before
        each problem to allow cooperative cancellation by an embedding process
        such as the web UI task manager. Defaults preserve existing CLI behavior.
        """
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
        aborted = False

        for size in campaign.problem_sizes:
            if should_abort is not None and should_abort():
                aborted = True
                break
            for seed in campaign.problem_seeds:
                if should_abort is not None and should_abort():
                    aborted = True
                    break
                key = (size, seed)
                if key not in generated_problems:
                    generated_problems[key] = _generate_problem(
                        campaign.family, size, seed, campaign.generator_parameters
                    )
                problem = generated_problems[key]
                problem_path = self.problems_dir / f"{problem.problem_id}.json"
                if problem_path.exists():
                    if load_problem(problem_path).identity_payload() != problem.identity_payload():
                        raise ValidationError(f"Existing problem artifact differs: {problem_path}")
                else:
                    save_problem(problem, problem_path)

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
                    continue

                def recorded(run: ExperimentRun) -> None:
                    all_runs.append(run)
                    status = run.result.status.value
                    summary_statuses[status] += 1
                    self.store.record_run(
                        campaign_id,
                        run.run_id,
                        status,
                        run.result.solver_name,
                        run.result.problem_id,
                        run.created_at,
                    )
                    if on_run_recorded is not None:
                        on_run_recorded(run, len(all_runs))

                self.runner.benchmark(
                    problem,
                    [solver_instances[name] for name in configs],
                    configs,
                    repeats=campaign.repeats,
                    on_persisted=recorded,
                    campaign_id=campaign_id,
                    web_task_id=web_task_id,
                    should_abort=should_abort,
                )
                if should_abort is not None and should_abort():
                    aborted = True
                    break

        if aborted:
            summary_statuses["aborted"] = 1
            return {
                "campaign_id": campaign_id,
                "name": campaign.name,
                "family": campaign.family,
                "requested_runs": requested,
                "completed_runs": len(all_runs),
                "status_summary": summary_statuses,
                "problem_ids": sorted({run.result.problem_id for run in all_runs}),
                "run_ids": [run.run_id for run in all_runs],
                "aborted": True,
            }

        return {
            "campaign_id": campaign_id,
            "name": campaign.name,
            "family": campaign.family,
            "requested_runs": requested,
            "completed_runs": len(all_runs),
            "status_summary": summary_statuses,
            "problem_ids": sorted({run.result.problem_id for run in all_runs}),
            "run_ids": [run.run_id for run in all_runs],
            "skipped_runs": summary_statuses["skipped"],
        }
