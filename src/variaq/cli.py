from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from variaq import __version__
from variaq.adapter_scaffold import init_adapter
from variaq.analysis.models import AnalysisQuery
from variaq.analysis.operations import analyze_runs
from variaq.analysis.reports import export_report, generate_report
from variaq.campaigns.model import DEFAULT_MAX_RUNS, ExperimentCampaign
from variaq.campaigns.plan import CampaignPlan
from variaq.campaigns.runner import CampaignRunner
from variaq.campaigns.store import CampaignStore
from variaq.capabilities import gather_capabilities, render_capabilities_human
from variaq.errors import ValidationError, VariaQError
from variaq.experiments.runner import ExperimentRunner
from variaq.experiments.storage import ExperimentStore
from variaq.models import ExperimentRun, SolverConfig, SolveStatus
from variaq.outputs import (
    benchmark_json_data,
    quantum_comparison_json_data,
    reproduction_json_data,
    result_warnings,
    run_status_for_exit,
    solve_json_data,
)
from variaq.problems.assignment import AssignmentProblem
from variaq.problems.base import ProblemInstance, load_problem, save_problem
from variaq.problems.graph_partition import GraphPartitionProblem
from variaq.problems.maxcut import MaxCutProblem
from variaq.problems.subset_selection import SubsetSelectionProblem
from variaq.serialization import (
    StructuredError,
    StructuredWarning,
    error_envelope,
    partial_envelope,
    success_envelope,
)
from variaq.solvers.base import get_solver, solver_names

DEFAULT_DB = Path("data/variaq.sqlite3")
LEGACY_DEFAULT_DB = Path("data/qlab.sqlite3")
DEFAULT_PROBLEMS_DIR = Path("data/problems")


def _default_db_path() -> Path:
    """Prefer new VariaQ state while discovering the pre-release legacy default."""
    if not DEFAULT_DB.exists() and LEGACY_DEFAULT_DB.exists():
        return LEGACY_DEFAULT_DB
    return DEFAULT_DB


def _json_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _parameters(values: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        if "=" not in value:
            raise ValidationError(f"Parameter must use KEY=VALUE: {value!r}")
        key, raw = value.split("=", 1)
        if not key:
            raise ValidationError("Parameter key cannot be empty")
        if key in result:
            raise ValidationError(f"Duplicate parameter: {key}")
        result[key] = _json_value(raw)
    return result


def _solver_parameters(values: list[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = defaultdict(dict)
    for value in values:
        if "=" not in value or "." not in value.split("=", 1)[0]:
            raise ValidationError(f"Solver parameter must use SOLVER.KEY=VALUE: {value!r}")
        qualified_key, raw = value.split("=", 1)
        solver_name, key = qualified_key.split(".", 1)
        solver_name = get_solver(solver_name).name
        if key in result[solver_name]:
            raise ValidationError(f"Duplicate solver parameter: {qualified_key}")
        result[solver_name][key] = _json_value(raw)
    return dict(result)


def _resolve_problem(reference: str, problems_dir: Path) -> ProblemInstance:
    candidate = Path(reference)
    if not candidate.exists():
        candidate = problems_dir / f"{reference}.json"
    if not candidate.exists():
        raise ValidationError(f"Problem not found: {reference}")
    return load_problem(candidate)


def _format_number(value: float | None, precision: int = 6) -> str:
    if value is None:
        return "-"
    return f"{value:.{precision}g}"


def _error_type(result) -> str:
    if result.errors:
        first = result.errors[0]
        inferred = type(first).__name__
        if inferred == "str":
            # Runner stores errors as "TypeName: message" strings.
            return first.split(":", 1)[0]
        return inferred
    return "SolverError"


def _json_flag() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--json", action="store_true", help="Emit structured JSON on stdout")
    return parser


def _print_runs(runs: list[ExperimentRun]) -> None:
    headers = ("solver", "status", "objective", "best", "gap %", "wall s", "backend", "run id")
    rows = [
        (
            run.result.solver_name,
            run.result.status.value,
            _format_number(run.result.objective),
            _format_number(run.result.best_known_objective),
            _format_number(run.result.optimality_gap_percent, 4),
            _format_number(run.result.wall_time_seconds, 5),
            run.result.backend.name,
            run.run_id,
        )
        for run in runs
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def _print_aggregates(runs: list[ExperimentRun]) -> None:
    grouped: dict[str, list[ExperimentRun]] = defaultdict(list)
    for run in runs:
        grouped[run.result.solver_name].append(run)
    if not any(len(group) > 1 for group in grouped.values()):
        return
    print("\nRepeated-run summary:")
    for solver_name, group in grouped.items():
        successful = [
            run
            for run in group
            if run.result.status is SolveStatus.SUCCESS and run.result.objective is not None
        ]
        unavailable = sum(run.result.status is SolveStatus.UNAVAILABLE for run in group)
        attempted = len(group) - unavailable
        if not successful:
            print(
                f"  {solver_name}: no successful runs"
                + (f", unavailable={unavailable}" if unavailable else "")
            )
            continue
        objectives = [float(run.result.objective) for run in successful]
        runtimes = [run.result.wall_time_seconds for run in successful]
        objective_std = statistics.pstdev(objectives) if len(objectives) > 1 else 0.0
        runtime_std = statistics.pstdev(runtimes) if len(runtimes) > 1 else 0.0
        optimum = next(
            (
                run.result.best_known_objective
                for run in successful
                if run.result.best_known_objective is not None
            ),
            None,
        )
        optimum_hits = (
            sum(abs(float(run.result.objective) - optimum) <= 1e-9 for run in successful)
            if optimum is not None
            else 0
        )
        optimum_rate = (
            optimum_hits / attempted * 100.0 if attempted and optimum is not None else None
        )
        print(
            f"  {solver_name}: successful={len(successful)}/{attempted}, "
            f"objective mean={statistics.mean(objectives):.6g} std={objective_std:.6g}, "
            f"best={max(objectives):.6g} worst={min(objectives):.6g}, "
            f"wall mean={statistics.mean(runtimes):.6g}s std={runtime_std:.6g}s"
            + (f", optimum success={optimum_rate:.1f}%" if optimum_rate is not None else "")
            + (f", unavailable={unavailable}" if unavailable else "")
        )


def _print_problem_summary(problem: ProblemInstance, runs: list[ExperimentRun]) -> None:
    reference = next(
        (
            (run.result.best_known_objective, run.result.best_known_source)
            for run in runs
            if run.result.best_known_objective is not None
        ),
        (None, None),
    )
    value, source = reference
    label = "optimum" if source in {"exact_optimum", "stored_exact_optimum"} else "reference"
    detail = ""
    if isinstance(problem, MaxCutProblem):
        detail = f"nodes={problem.node_count} edges={len(problem.edges)}"
    elif isinstance(problem, AssignmentProblem):
        detail = f"tasks={len(problem.task_ids)} resources={len(problem.resource_ids)}"
    elif isinstance(problem, SubsetSelectionProblem):
        detail = f"candidates={len(problem.candidate_ids)}"
    elif isinstance(problem, GraphPartitionProblem):
        detail = (
            f"nodes={len(problem.node_ids)} edges={len(problem.edges)} "
            f"partitions={problem.partition_count}"
        )
    print(
        f"Problem: {problem.problem_id}  family={problem.family} {detail} "
        f"{label}={_format_number(value)}"
    )


def _print_quantum_comparison(runs: list[ExperimentRun]) -> None:
    print("\nMatched quantum detail:")
    by_seed: dict[int, list[ExperimentRun]] = defaultdict(list)
    for run in runs:
        by_seed[run.result.seed].append(run)
    for seed, group in sorted(by_seed.items()):
        successful = [run for run in group if run.result.status is SolveStatus.SUCCESS]
        unavailable = [run for run in group if run.result.status is SolveStatus.UNAVAILABLE]
        digests = {
            str(run.result.backend.metrics.get("candidate_parameter_digest")) for run in successful
        }
        max_delta = 0.0
        if len(successful) > 1:
            reference = successful[0].result.backend.metrics.get("candidate_expectations", [])
            for run in successful[1:]:
                candidate = run.result.backend.metrics.get("candidate_expectations", [])
                if len(candidate) == len(reference):
                    max_delta = max(
                        max_delta,
                        max(
                            (
                                abs(float(a) - float(b))
                                for a, b in zip(reference, candidate, strict=True)
                            ),
                            default=0.0,
                        ),
                    )
        best_indices = {
            run.result.solver_name: run.result.backend.metrics.get("best_parameter_index")
            for run in successful
        }
        print(
            f"  seed={seed}: identical_candidates={'yes' if len(digests) <= 1 else 'NO'}, "
            f"max_expectation_delta={max_delta:.3g}, best_parameter_indices={best_indices}"
        )
        for run in unavailable:
            reason = run.result.backend.metrics.get("reason", "unavailable")
            print(f"    {run.result.solver_name}: unavailable ({reason})")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="variaq",
        description=(
            "Local-first reproducible classical, GPU-accelerated, and quantum experiments"
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--db", type=Path, default=_default_db_path(), help="SQLite experiment database"
    )
    parser.add_argument(
        "--problems-dir", type=Path, default=DEFAULT_PROBLEMS_DIR, help="Saved problem directory"
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    problem = subcommands.add_parser("problem", help="Create and inspect problem instances")
    problem_commands = problem.add_subparsers(dest="problem_command", required=True)
    generate = problem_commands.add_parser(
        "generate", help="Generate a deterministic problem", parents=[_json_flag()]
    )
    generate.add_argument(
        "problem_type",
        choices=["maxcut", "assignment", "subset-selection", "graph-partition"],
    )
    generate.add_argument("--nodes", type=int)
    generate.add_argument("--task-count", type=int)
    generate.add_argument("--resource-count", type=int)
    generate.add_argument("--candidate-count", type=int)
    generate.add_argument("--budget", type=float)
    generate.add_argument("--min-cardinality", type=int)
    generate.add_argument("--max-cardinality", type=int)
    generate.add_argument("--edge-probability", type=float)
    generate.add_argument("--partition-count", type=int)
    generate.add_argument("--min-partition-size", type=int)
    generate.add_argument("--max-partition-size", type=int)
    generate.add_argument("--seed", type=int, required=True)
    generate.add_argument("--output", type=Path)
    import_problem = problem_commands.add_parser(
        "import", help="Import a problem artifact", parents=[_json_flag()]
    )
    import_problem.add_argument("input")
    import_problem.add_argument("--output", type=Path)

    show_problem = problem_commands.add_parser(
        "show", help="Show a saved problem", parents=[_json_flag()]
    )
    show_problem.add_argument("problem")

    solve = subcommands.add_parser(
        "solve", help="Run one solver and persist the result", parents=[_json_flag()]
    )
    solve.add_argument("problem")
    solve.add_argument("--solver", choices=solver_names(), required=True)
    solve.add_argument("--seed", type=int, default=0)
    solve.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")

    benchmark = subcommands.add_parser(
        "benchmark", help="Compare solvers on one exact instance", parents=[_json_flag()]
    )
    benchmark.add_argument("problem")
    benchmark.add_argument("--solvers", default="exact,heuristic,qaoa")
    benchmark.add_argument("--seed", type=int, default=0)
    benchmark.add_argument("--repeats", type=int, default=1)
    benchmark.add_argument(
        "--solver-param", action="append", default=[], metavar="SOLVER.KEY=VALUE"
    )

    suite = subcommands.add_parser(
        "suite", help="Run an opt-in deterministic benchmark suite", parents=[_json_flag()]
    )
    suite.add_argument("--config", type=Path, default=Path("benchmarks/maxcut_v0.1.json"))
    suite.add_argument("--solvers", help="Override comma-separated solvers from config")
    suite.add_argument("--repeats", type=int, default=1)
    suite.add_argument("--solver-param", action="append", default=[], metavar="SOLVER.KEY=VALUE")

    adapter = subcommands.add_parser("adapter", help="Scaffold external domain adapters")
    adapter_commands = adapter.add_subparsers(dest="adapter_command", required=True)
    adapter_init = adapter_commands.add_parser(
        "init", help="Scaffold a small domain adapter template", parents=[_json_flag()]
    )
    adapter_init.add_argument("name")
    adapter_init.add_argument("--family", choices=["assignment", "subset-selection"], required=True)
    adapter_init.add_argument("--output", type=Path, default=Path("my-adapter"))

    subcommands.add_parser(
        "capabilities", help="Report solver and framework availability", parents=[_json_flag()]
    )

    compare = subcommands.add_parser("compare", help="Run controlled cross-framework comparisons")
    compare_commands = compare.add_subparsers(dest="compare_command", required=True)
    compare_quantum = compare_commands.add_parser(
        "quantum", help="Compare matched QAOA implementations", parents=[_json_flag()]
    )
    compare_quantum.add_argument("problem")
    compare_quantum.add_argument("--solvers", default="qaoa,cudaq-cpu,cudaq-gpu")
    compare_quantum.add_argument("--p", type=int, default=1)
    compare_quantum.add_argument("--optimizer-trials", type=int, default=32)
    compare_quantum.add_argument("--shots", type=int, default=1024)
    compare_quantum.add_argument("--seed", type=int, default=42)
    compare_quantum.add_argument("--repeats", type=int, default=1)
    compare_quantum.add_argument("--warmup", action=argparse.BooleanOptionalAction, default=False)
    compare_quantum.add_argument("--gpu-precision", choices=("fp32", "fp64"), default="fp32")

    campaign = subcommands.add_parser("campaign", help="Plan, run, and list experiment campaigns")
    campaign_commands = campaign.add_subparsers(dest="campaign_command", required=True)
    campaign_plan = campaign_commands.add_parser("plan", parents=[_json_flag()])
    campaign_plan.add_argument("campaign_file", type=Path)
    campaign_run = campaign_commands.add_parser("run", parents=[_json_flag()])
    campaign_run.add_argument("campaign_file", type=Path)
    campaign_run.add_argument("--override-max-runs", action="store_true")
    campaign_run.add_argument("--max-runs", type=int, default=DEFAULT_MAX_RUNS)
    campaign_list = campaign_commands.add_parser("list", parents=[_json_flag()])
    campaign_list.add_argument("--limit", type=int, default=100)
    campaign_show = campaign_commands.add_parser("show", parents=[_json_flag()])
    campaign_show.add_argument("campaign_id")

    analyze = subcommands.add_parser("analyze", help="Analyze stored experiment runs")
    analyze_commands = analyze.add_subparsers(dest="analyze_command", required=True)
    analyze_runs_parser = analyze_commands.add_parser("runs", parents=[_json_flag()])
    analyze_runs_parser.add_argument("--run-id", action="append", default=[])
    analyze_runs_parser.add_argument("--group-by", action="append", default=[])
    analyze_runs_parser.add_argument("--filter", action="append", default=[], metavar="KEY=VALUE")
    analyze_runs_parser.add_argument("--scaling-x", default="problem_size")
    analyze_runs_parser.add_argument("--include-failed", action="store_true")
    analyze_runs_parser.add_argument("--include-unavailable", action="store_true")
    analyze_campaign = analyze_commands.add_parser("campaign", parents=[_json_flag()])
    analyze_campaign.add_argument("campaign_id")
    analyze_campaign.add_argument("--group-by", action="append", default=[])
    analyze_campaign.add_argument("--scaling-x", default="problem_size")
    analyze_campaign.add_argument("--include-failed", action="store_true")
    analyze_campaign.add_argument("--include-unavailable", action="store_true")
    analyze_campaign.add_argument(
        "--compare",
        action="append",
        default=[],
        choices=["classical_vs_quantum", "qiskit_vs_cudaq", "gpu_vs_cpu"],
    )

    report = subcommands.add_parser("report", help="Generate reports from analysis results")
    report_commands = report.add_subparsers(dest="report_command", required=True)
    report_campaign = report_commands.add_parser("campaign", parents=[_json_flag()])
    report_campaign.add_argument("campaign_id")
    report_campaign.add_argument("--output-dir", type=Path, required=True)
    report_campaign.add_argument("--formats", default="json,csv,markdown")
    report_campaign.add_argument("--group-by", action="append", default=[])
    report_campaign.add_argument("--scaling-x", default="problem_size")
    report_campaign.add_argument("--overwrite", action="store_true")
    report_campaign.add_argument("--plots", action="store_true")
    report_campaign.add_argument(
        "--compare",
        action="append",
        default=[],
        choices=["classical_vs_quantum", "qiskit_vs_cudaq", "gpu_vs_cpu"],
    )

    runs = subcommands.add_parser("runs", help="Inspect or reproduce durable experiment runs")
    runs_commands = runs.add_subparsers(dest="runs_command", required=True)
    list_runs = runs_commands.add_parser("list", parents=[_json_flag()])
    list_runs.add_argument("--limit", type=int, default=20)
    show_run = runs_commands.add_parser("show", parents=[_json_flag()])
    show_run.add_argument("run_id")
    reproduce = runs_commands.add_parser("reproduce", parents=[_json_flag()])
    reproduce.add_argument("run_id")

    web = subcommands.add_parser(
        "web", help="Start the optional local web UI (requires the 'web' extra)"
    )
    web.add_argument("--host", default=None, help="Bind address (default: 127.0.0.1)")
    web.add_argument("--port", type=int, default=None, help="Port (default: 8701)")
    web.add_argument(
        "--reports-dir",
        type=Path,
        default=None,
        help="Report output root (default: data/reports)",
    )
    return parser


def _generate_problem(args: argparse.Namespace) -> ProblemInstance:
    family = args.problem_type
    if family == "maxcut":
        if args.nodes is None or args.edge_probability is None:
            raise ValidationError("maxcut requires --nodes and --edge-probability")
        return MaxCutProblem.generate(args.nodes, args.edge_probability, args.seed)
    if family == "assignment":
        if args.task_count is None or args.resource_count is None:
            raise ValidationError("assignment requires --task-count and --resource-count")
        return AssignmentProblem.generate(args.task_count, args.resource_count, args.seed)
    if family == "subset-selection":
        if args.candidate_count is None:
            raise ValidationError("subset-selection requires --candidate-count")
        return SubsetSelectionProblem.generate(
            args.candidate_count,
            args.seed,
            budget=args.budget,
            min_cardinality=args.min_cardinality,
            max_cardinality=args.max_cardinality,
        )
    if family == "graph-partition":
        if args.nodes is None or args.edge_probability is None or args.partition_count is None:
            raise ValidationError(
                "graph-partition requires --nodes, --edge-probability, and --partition-count"
            )
        return GraphPartitionProblem.generate(
            args.nodes,
            args.edge_probability,
            args.partition_count,
            args.seed,
            min_partition_size=args.min_partition_size,
            max_partition_size=args.max_partition_size,
        )
    raise ValidationError(f"Unsupported problem type: {family!r}")


def _command_adapter(args: argparse.Namespace) -> int:
    paths = init_adapter(args.name, args.family, args.output)
    if args.json:
        print(success_envelope(command="adapter init", data={"files": [str(p) for p in paths]}))
        return 0
    print(f"Scaffolded adapter in {args.output}")
    for path in paths:
        print(f"  {path}")
    return 0


def _command_problem(args: argparse.Namespace) -> int:
    if args.problem_command == "generate":
        generated = _generate_problem(args)
        output = args.output or args.problems_dir / f"{generated.problem_id}.json"
        save_problem(generated, output)
        data: dict[str, Any] = {
            "problem_id": generated.problem_id,
            "problem_type": generated.problem_type,
            "family": generated.family,
            "seed": args.seed,
            "path": str(output),
        }
        if isinstance(generated, MaxCutProblem):
            data["node_count"] = generated.node_count
            data["edge_count"] = len(generated.edges)
        elif isinstance(generated, AssignmentProblem):
            data["task_count"] = len(generated.task_ids)
            data["resource_count"] = len(generated.resource_ids)
        elif isinstance(generated, SubsetSelectionProblem):
            data["candidate_count"] = len(generated.candidate_ids)
        elif isinstance(generated, GraphPartitionProblem):
            data["node_count"] = len(generated.node_ids)
            data["edge_count"] = len(generated.edges)
            data["partition_count"] = generated.partition_count
        if args.json:
            print(success_envelope(command="problem generate", data=data))
            return 0
        print(f"Saved {generated.problem_id} to {output}")
        print(f"family={generated.family} seed={args.seed}")
        return 0
    if args.problem_command == "import":
        target = Path(args.input)
        if not target.exists():
            raise ValidationError(f"Import source not found: {target}")
        imported = load_problem(target)
        output = args.output or args.problems_dir / f"{imported.problem_id}.json"
        save_problem(imported, output)
        if args.json:
            print(
                success_envelope(
                    command="problem import",
                    data={"problem_id": imported.problem_id, "path": str(output)},
                )
            )
            return 0
        print(f"Imported {imported.problem_id} to {output}")
        return 0
    problem = _resolve_problem(args.problem, args.problems_dir)
    if args.json:
        print(success_envelope(command="problem show", data=problem.to_dict()))
        return 0
    print(json.dumps(problem.to_dict(), indent=2, sort_keys=True))
    return 0


def _command_solve(args: argparse.Namespace, runner: ExperimentRunner) -> int:
    problem = _resolve_problem(args.problem, args.problems_dir)
    solver = get_solver(args.solver)
    if problem.family not in solver.supported_families:
        if args.json:
            print(
                error_envelope(
                    command="solve",
                    error=StructuredError(
                        type="UnsupportedFamilyError",
                        message=(
                            f"Solver {solver.name!r} does not support family {problem.family!r}"
                        ),
                    ),
                )
            )
        else:
            print(
                f"error: Solver {solver.name!r} does not support family {problem.family!r}",
                file=sys.stderr,
            )
        return 2
    run = runner.run_one(
        problem,
        solver,
        SolverConfig(seed=args.seed, parameters=_parameters(args.param)),
    )
    if args.json:
        if run.result.status is SolveStatus.FAILED:
            print(
                error_envelope(
                    command="solve",
                    error=StructuredError(
                        type=_error_type(run.result),
                        message=run.result.errors[0] if run.result.errors else "solver failed",
                        run_id=run.run_id,
                    ),
                    data=solve_json_data(run),
                    warnings=result_warnings(run.result),
                )
            )
            return 1
        if run.result.status is SolveStatus.UNAVAILABLE:
            print(
                success_envelope(
                    command="solve",
                    data=solve_json_data(run),
                    warnings=result_warnings(run.result),
                )
            )
            return 0
        print(success_envelope(command="solve", data=solve_json_data(run)))
        return 0
    _print_runs([run])
    if run.result.status is SolveStatus.FAILED:
        print(f"error: {run.result.errors[0]}", file=sys.stderr)
        return 1
    if run.result.status is SolveStatus.UNAVAILABLE:
        print(f"unavailable: {run.result.warnings[0]}", file=sys.stderr)
    return 0


def _selected_solvers(value: str) -> list[Any]:
    names = [name.strip() for name in value.split(",") if name.strip()]
    if not names:
        raise ValidationError("At least one solver is required")
    canonical = [get_solver(name) for name in names]
    if len({solver.name for solver in canonical}) != len(canonical):
        raise ValidationError("Solver list contains duplicates")
    return canonical


def _configs(solvers: list[Any], seed: int, values: list[str]) -> dict[str, SolverConfig]:
    per_solver = _solver_parameters(values)
    selected = {solver.name for solver in solvers}
    unused = set(per_solver) - selected
    if unused:
        raise ValidationError(f"Parameters supplied for unselected solvers: {sorted(unused)}")
    return {
        solver.name: SolverConfig(seed=seed, parameters=per_solver.get(solver.name, {}))
        for solver in solvers
    }


def _command_benchmark(args: argparse.Namespace, runner: ExperimentRunner) -> int:
    problem = _resolve_problem(args.problem, args.problems_dir)
    solvers = _selected_solvers(args.solvers)
    unsupported = [
        solver.name for solver in solvers if problem.family not in solver.supported_families
    ]
    if unsupported:
        message = f"Solvers {unsupported!r} do not support problem family {problem.family!r}"
        if args.json:
            print(
                error_envelope(
                    command="benchmark",
                    error=StructuredError(
                        type="UnsupportedFamilyError",
                        message=message,
                    ),
                )
            )
        else:
            print(f"error: {message}", file=sys.stderr)
        return 2
    runs = runner.benchmark(
        problem,
        solvers,
        _configs(solvers, args.seed, args.solver_param),
        repeats=args.repeats,
    )
    if args.json:
        data = benchmark_json_data(problem, runs)
        failed = [run for run in runs if run.result.status is SolveStatus.FAILED]
        unavailable = [run for run in runs if run.result.status is SolveStatus.UNAVAILABLE]
        warnings: list[StructuredWarning] = []
        for run in unavailable:
            for message in run.result.warnings:
                warnings.append(
                    StructuredWarning(
                        type="backend_unavailable",
                        message=message,
                        context={"solver": run.result.solver_name, "run_id": run.run_id},
                    )
                )
        if failed:
            first = failed[0]
            print(
                partial_envelope(
                    command="benchmark",
                    data=data,
                    error=StructuredError(
                        type=_error_type(first.result),
                        message=first.result.errors[0]
                        if first.result.errors
                        else "at least one solver failed",
                        run_id=first.run_id,
                        context={"failed_solvers": [run.result.solver_name for run in failed]},
                    ),
                    warnings=tuple(warnings),
                )
            )
        else:
            print(success_envelope(command="benchmark", data=data, warnings=tuple(warnings)))
        return run_status_for_exit(runs)
    _print_problem_summary(problem, runs)
    _print_runs(runs)
    _print_aggregates(runs)
    return run_status_for_exit(runs)


def _command_suite(args: argparse.Namespace, runner: ExperimentRunner) -> int:
    try:
        suite = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Could not load suite config {args.config}: {exc}") from exc
    solver_value = args.solvers or ",".join(suite["solvers"])
    solvers = _selected_solvers(solver_value)
    all_runs: list[ExperimentRun] = []
    for instance in suite["instances"]:
        problem = MaxCutProblem.generate(
            node_count=int(instance["nodes"]),
            edge_probability=float(instance["edge_probability"]),
            seed=int(instance["seed"]),
        )
        print(f"\n{problem.problem_id}: nodes={problem.node_count}, edges={len(problem.edges)}")
        runs = runner.benchmark(
            problem,
            solvers,
            _configs(solvers, int(instance["seed"]), args.solver_param),
            repeats=args.repeats,
        )
        _print_problem_summary(problem, runs)
        _print_runs(runs)
        _print_aggregates(runs)
        all_runs.extend(runs)
    return run_status_for_exit(all_runs)


def _command_capabilities(args: argparse.Namespace) -> int:
    data = gather_capabilities()
    if args.json:
        print(success_envelope(command="capabilities", data=data, warnings=tuple()))
        return 0
    print(render_capabilities_human(data))
    return 0


def _command_compare(args: argparse.Namespace, runner: ExperimentRunner) -> int:
    if args.p < 1 or args.optimizer_trials < 1 or args.shots < 1 or args.repeats < 1:
        raise ValidationError("p, optimizer-trials, shots, and repeats must be positive")
    problem = _resolve_problem(args.problem, args.problems_dir)
    solvers = _selected_solvers(args.solvers)
    invalid = [
        solver.name for solver in solvers if solver.name not in {"qaoa", "cudaq-cpu", "cudaq-gpu"}
    ]
    if invalid:
        raise ValidationError(f"compare quantum accepts QAOA solvers only: {invalid}")
    for solver in solvers:
        if problem.family not in solver.supported_families:
            if args.json:
                print(
                    error_envelope(
                        command="compare quantum",
                        error=StructuredError(
                            type="UnsupportedFamilyError",
                            message=(
                                f"Solver {solver.name!r} does not support family {problem.family!r}"
                            ),
                        ),
                    )
                )
            else:
                print(
                    f"error: Solver {solver.name!r} does not support family {problem.family!r}",
                    file=sys.stderr,
                )
            return 2
    common = {
        "p": args.p,
        "optimizer_trials": args.optimizer_trials,
        "shots": args.shots,
        "warmup": args.warmup,
    }
    configs: dict[str, SolverConfig] = {}
    for solver in solvers:
        parameters = dict(common)
        if solver.name == "cudaq-cpu":
            parameters["precision"] = "fp64"
        elif solver.name == "cudaq-gpu":
            parameters["precision"] = args.gpu_precision
        configs[solver.name] = SolverConfig(seed=args.seed, parameters=parameters)
    runs = runner.benchmark(problem, solvers, configs, repeats=args.repeats)
    if args.json:
        data = quantum_comparison_json_data(problem, runs)
        failed = [run for run in runs if run.result.status is SolveStatus.FAILED]
        unavailable = [run for run in runs if run.result.status is SolveStatus.UNAVAILABLE]
        warnings: list[StructuredWarning] = []
        for run in unavailable:
            for message in run.result.warnings:
                warnings.append(
                    StructuredWarning(
                        type="backend_unavailable",
                        message=message,
                        context={"solver": run.result.solver_name, "run_id": run.run_id},
                    )
                )
        if failed:
            first = failed[0]
            print(
                partial_envelope(
                    command="compare quantum",
                    data=data,
                    error=StructuredError(
                        type=_error_type(first.result),
                        message=first.result.errors[0]
                        if first.result.errors
                        else "at least one solver failed",
                        run_id=first.run_id,
                        context={"failed_solvers": [run.result.solver_name for run in failed]},
                    ),
                    warnings=tuple(warnings),
                )
            )
        else:
            print(success_envelope(command="compare quantum", data=data, warnings=tuple(warnings)))
        return run_status_for_exit(runs)
    _print_problem_summary(problem, runs)
    _print_runs(runs)
    _print_quantum_comparison(runs)
    _print_aggregates(runs)
    return run_status_for_exit(runs)


def _filter_parameters(values: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        if "=" not in value:
            raise ValidationError(f"Filter must use KEY=VALUE: {value!r}")
        key, raw = value.split("=", 1)
        if not key:
            raise ValidationError("Filter key cannot be empty")
        result[key] = _json_value(raw)
    return result


def _command_campaign(
    args: argparse.Namespace, runner: ExperimentRunner, campaign_store: CampaignStore
) -> int:
    if args.campaign_command == "list":
        rows = campaign_store.list_campaigns(args.limit)
        if args.json:
            print(success_envelope(command="campaign list", data=rows))
            return 0
        print("Campaigns:")
        for row in rows:
            print(f"  {row['campaign_id']} {row['name']} ({row['family']}) {row['created_at']}")
        return 0
    if args.campaign_command == "show":
        campaign = campaign_store.get_campaign(args.campaign_id)
        if args.json:
            print(success_envelope(command="campaign show", data=campaign.to_dict()))
            return 0
        print(json.dumps(campaign.to_dict(), indent=2, sort_keys=True))
        return 0

    campaign = ExperimentCampaign.from_dict(
        json.loads(args.campaign_file.read_text(encoding="utf-8"))
    )
    if args.campaign_command == "plan":
        plan = CampaignPlan(campaign).build()
        if args.json:
            print(success_envelope(command="campaign plan", data=plan))
            return 0
        print(f"Campaign plan: {plan['name']}")
        print(f"  family: {plan['family']}")
        print(f"  problem instances: {plan['problem_instance_count']}")
        print(f"  requested runs: {plan['requested_runs']}")
        print(f"  estimated quantum runs: {plan['estimated_quantum_runs']}")
        print(f"  max binary variables: {plan['max_binary_variables']}")
        for entry in plan["solver_breakdown"]:
            print(
                f"    {entry['solver']}: {entry['requested_runs']} runs "
                f"(available={entry['available']})"
            )
        for warning in plan["warnings"]:
            print(f"  warning: {warning}")
        return 0

    cr = CampaignRunner(runner, campaign_store, args.problems_dir, max_runs=args.max_runs)
    summary = cr.run(campaign, override_max_runs=args.override_max_runs)
    if args.json:
        print(success_envelope(command="campaign run", data=summary))
        return 0
    print(f"Campaign {summary['campaign_id']} completed")
    print(f"  requested: {summary['requested_runs']}")
    print(f"  completed: {summary['completed_runs']}")
    for status, count in summary["status_summary"].items():
        print(f"  {status}: {count}")
    return 0


def _command_analyze(
    args: argparse.Namespace, store: ExperimentStore, campaign_store: CampaignStore
) -> int:
    run_ids: list[str] = []
    campaign_id: str | None = None
    if args.analyze_command == "campaign":
        campaign_id = args.campaign_id
        run_ids = campaign_store.get_run_ids(campaign_id)
    else:
        run_ids = list(args.run_id)
        if not run_ids:
            # If no explicit run IDs, analyze all stored runs
            limit = args.limit if hasattr(args, "limit") else 1000
            summaries = store.list_runs(limit=limit)
            run_ids = [s["run_id"] for s in summaries]
    if not run_ids:
        if args.json:
            print(
                error_envelope(
                    command=f"analyze {args.analyze_command}",
                    error=StructuredError(
                        type="NoRunsError", message="No runs selected for analysis"
                    ),
                )
            )
        else:
            print("error: No runs selected for analysis", file=sys.stderr)
        return 2

    runs = [store.get(rid) for rid in run_ids]
    query = AnalysisQuery(
        campaign_id=campaign_id,
        run_ids=tuple(run_ids),
        filters=_filter_parameters(args.filter) if hasattr(args, "filter") else {},
        group_by=tuple(args.group_by) if args.group_by else (),
        include_failed=args.include_failed,
        include_unavailable=args.include_unavailable,
    )
    comparisons = tuple(args.compare) if hasattr(args, "compare") else ()
    result = analyze_runs(runs, query, scaling_x_metric=args.scaling_x, comparisons=comparisons)
    if args.json:
        print(success_envelope(command=f"analyze {args.analyze_command}", data=result.to_dict()))
        return 0
    print(f"Analysis: {len(result.groups)} groups, {len(result.scaling_points)} scaling points")
    for group in result.groups:
        key = ", ".join(f"{k}={v}" for k, v in group.group_key.items())
        print(f"  {key}: count={group.count} best={group.quality.best_objective}")
    return 0


def _command_report(
    args: argparse.Namespace, store: ExperimentStore, campaign_store: CampaignStore
) -> int:
    run_ids = campaign_store.get_run_ids(args.campaign_id)
    if not run_ids:
        if args.json:
            print(
                error_envelope(
                    command="report campaign",
                    error=StructuredError(
                        type="NoRunsError", message=f"Campaign {args.campaign_id!r} has no runs"
                    ),
                )
            )
        else:
            print(f"error: Campaign {args.campaign_id!r} has no runs", file=sys.stderr)
        return 2
    runs = [store.get(rid) for rid in run_ids]
    query = AnalysisQuery(
        campaign_id=args.campaign_id,
        run_ids=tuple(run_ids),
        group_by=tuple(args.group_by) if args.group_by else ("problem_id", "solver"),
        include_failed=True,
    )
    comparisons = tuple(args.compare) if args.compare else ()
    analysis = analyze_runs(runs, query, scaling_x_metric=args.scaling_x, comparisons=comparisons)
    report = generate_report(analysis, campaign_id=args.campaign_id)
    formats = tuple(f.strip() for f in args.formats.split(",") if f.strip())
    paths = export_report(report, args.output_dir, formats=formats, overwrite=args.overwrite)
    if args.plots:
        try:
            plot_paths = export_report(
                report, args.output_dir, formats=("plots",), overwrite=args.overwrite
            )
            paths["plots"] = plot_paths.get("plots", {})
        except ImportError as exc:
            if args.json:
                print(
                    partial_envelope(
                        command="report campaign",
                        data={"report_id": report.report_id, "paths": paths},
                        warnings=(
                            StructuredWarning(
                                type="optional_dependency_missing",
                                message=f"Plotting skipped: {exc}",
                            ),
                        ),
                    )
                )
                return 0
            print(f"warning: plotting skipped: {exc}", file=sys.stderr)
    if args.json:
        print(
            success_envelope(
                command="report campaign", data={"report_id": report.report_id, "paths": paths}
            )
        )
        return 0
    print(f"Report {report.report_id} exported")
    for key, value in paths.items():
        print(f"  {key}: {value}")
    return 0


def _command_runs(
    args: argparse.Namespace, store: ExperimentStore, runner: ExperimentRunner
) -> int:
    if args.runs_command == "list":
        rows = store.list_runs(args.limit)
        if not rows:
            if args.json:
                print(success_envelope(command="runs list", data=rows))
                return 0
            print("No experiment runs recorded.")
            return 0
        print(success_envelope(command="runs list", data=rows))
        return 0
    if args.runs_command == "show":
        run = store.get(args.run_id)
        if args.json:
            print(success_envelope(command="runs show", data=run.to_dict()))
            return 0
        print(json.dumps(run.to_dict(), indent=2, sort_keys=True))
        return 0
    run = runner.reproduce(args.run_id)
    if args.json:
        original = store.get(args.run_id)
        print(
            success_envelope(command="runs reproduce", data=reproduction_json_data(original, run))
        )
        return run_status_for_exit([run])
    _print_runs([run])
    print(f"reproduced_from={args.run_id}")
    if run.result.status is SolveStatus.FAILED:
        print(f"error: {run.result.errors[0]}", file=sys.stderr)
        return 1
    return 0


def _command_web(args: argparse.Namespace) -> int:
    try:
        from variaq.web import web_dependencies_available
    except ImportError:
        web_dependencies_available = None
    if web_dependencies_available is None or not web_dependencies_available():
        message = (
            "The VariaQ web UI requires optional dependencies.\n"
            "Install VariaQ with the web extra:\n"
            "    pip install 'variaq[web]'"
        )
        print(message, file=sys.stderr)
        return 2
    from variaq.web.config import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_REPORTS_DIR, WebConfig
    from variaq.web.server import serve

    config = WebConfig(
        host=args.host or DEFAULT_HOST,
        port=args.port if args.port is not None else DEFAULT_PORT,
        db_path=args.db,
        problems_dir=args.problems_dir,
        reports_dir=args.reports_dir or DEFAULT_REPORTS_DIR,
    )
    return serve(config)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "problem":
            return _command_problem(args)
        if args.command == "adapter":
            return _command_adapter(args)
        if args.command == "capabilities":
            return _command_capabilities(args)
        if args.command == "web":
            return _command_web(args)
        store = ExperimentStore(args.db)
        campaign_store = CampaignStore(args.db)
        runner = ExperimentRunner(store)
        if args.command == "solve":
            return _command_solve(args, runner)
        if args.command == "benchmark":
            return _command_benchmark(args, runner)
        if args.command == "suite":
            return _command_suite(args, runner)
        if args.command == "compare":
            return _command_compare(args, runner)
        if args.command == "campaign":
            return _command_campaign(args, runner, campaign_store)
        if args.command == "analyze":
            return _command_analyze(args, store, campaign_store)
        if args.command == "report":
            return _command_report(args, store, campaign_store)
        return _command_runs(args, store, runner)
    except (VariaQError, FileExistsError, ValueError, KeyError) as exc:
        if getattr(args, "json", False):
            print(
                error_envelope(
                    command=getattr(args, "command", "variaq"),
                    error=StructuredError(
                        type=type(exc).__name__,
                        message=str(exc),
                    ),
                )
            )
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
