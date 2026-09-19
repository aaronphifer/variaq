from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from variaq import __version__
from variaq.errors import ValidationError, VariaQError
from variaq.experiments.runner import ExperimentRunner
from variaq.experiments.storage import ExperimentStore
from variaq.models import ExperimentRun, SolverConfig, SolveStatus
from variaq.problems.base import load_problem, save_problem
from variaq.problems.maxcut import MaxCutProblem
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


def _resolve_problem(reference: str, problems_dir: Path) -> MaxCutProblem:
    candidate = Path(reference)
    if not candidate.exists():
        candidate = problems_dir / f"{reference}.json"
    if not candidate.exists():
        raise ValidationError(f"Problem not found: {reference}")
    problem = load_problem(candidate)
    if not isinstance(problem, MaxCutProblem):
        raise ValidationError("The current VariaQ CLI supports MaxCut only")
    return problem


def _format_number(value: float | None, precision: int = 6) -> str:
    if value is None:
        return "-"
    return f"{value:.{precision}g}"


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


def _print_problem_summary(problem: MaxCutProblem, runs: list[ExperimentRun]) -> None:
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
    print(
        f"Problem: {problem.problem_id}  nodes={problem.node_count} "
        f"edges={len(problem.edges)}  {label}={_format_number(value)}"
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
    generate = problem_commands.add_parser("generate", help="Generate a deterministic problem")
    generate.add_argument("problem_type", choices=["maxcut"])
    generate.add_argument("--nodes", type=int, required=True)
    generate.add_argument("--edge-probability", type=float, required=True)
    generate.add_argument("--seed", type=int, required=True)
    generate.add_argument("--output", type=Path)
    show_problem = problem_commands.add_parser("show", help="Show a saved problem")
    show_problem.add_argument("problem")

    solve = subcommands.add_parser("solve", help="Run one solver and persist the result")
    solve.add_argument("problem")
    solve.add_argument("--solver", choices=solver_names(), required=True)
    solve.add_argument("--seed", type=int, default=0)
    solve.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")

    benchmark = subcommands.add_parser("benchmark", help="Compare solvers on one exact instance")
    benchmark.add_argument("problem")
    benchmark.add_argument("--solvers", default="exact,heuristic,qaoa")
    benchmark.add_argument("--seed", type=int, default=0)
    benchmark.add_argument("--repeats", type=int, default=1)
    benchmark.add_argument(
        "--solver-param", action="append", default=[], metavar="SOLVER.KEY=VALUE"
    )

    suite = subcommands.add_parser("suite", help="Run an opt-in deterministic benchmark suite")
    suite.add_argument("--config", type=Path, default=Path("benchmarks/maxcut_v0.1.json"))
    suite.add_argument("--solvers", help="Override comma-separated solvers from config")
    suite.add_argument("--repeats", type=int, default=1)
    suite.add_argument("--solver-param", action="append", default=[], metavar="SOLVER.KEY=VALUE")

    compare = subcommands.add_parser("compare", help="Run controlled cross-framework comparisons")
    compare_commands = compare.add_subparsers(dest="compare_command", required=True)
    compare_quantum = compare_commands.add_parser(
        "quantum", help="Compare matched QAOA implementations"
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

    runs = subcommands.add_parser("runs", help="Inspect or reproduce durable experiment runs")
    runs_commands = runs.add_subparsers(dest="runs_command", required=True)
    list_runs = runs_commands.add_parser("list")
    list_runs.add_argument("--limit", type=int, default=20)
    show_run = runs_commands.add_parser("show")
    show_run.add_argument("run_id")
    reproduce = runs_commands.add_parser("reproduce")
    reproduce.add_argument("run_id")
    return parser


def _command_problem(args: argparse.Namespace) -> int:
    if args.problem_command == "generate":
        generated = MaxCutProblem.generate(args.nodes, args.edge_probability, args.seed)
        output = args.output or args.problems_dir / f"{generated.problem_id}.json"
        save_problem(generated, output)
        print(f"Saved {generated.problem_id} to {output}")
        print(f"nodes={generated.node_count} edges={len(generated.edges)} seed={args.seed}")
        return 0
    generated = _resolve_problem(args.problem, args.problems_dir)
    print(json.dumps(generated.to_dict(), indent=2, sort_keys=True))
    return 0


def _command_solve(args: argparse.Namespace, runner: ExperimentRunner) -> int:
    problem = _resolve_problem(args.problem, args.problems_dir)
    solver = get_solver(args.solver)
    run = runner.run_one(
        problem,
        solver,
        SolverConfig(seed=args.seed, parameters=_parameters(args.param)),
    )
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
    runs = runner.benchmark(
        problem,
        solvers,
        _configs(solvers, args.seed, args.solver_param),
        repeats=args.repeats,
    )
    _print_problem_summary(problem, runs)
    _print_runs(runs)
    _print_aggregates(runs)
    return 1 if any(run.result.status is SolveStatus.FAILED for run in runs) else 0


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
    return 1 if any(run.result.status is SolveStatus.FAILED for run in all_runs) else 0


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
    _print_problem_summary(problem, runs)
    _print_runs(runs)
    _print_quantum_comparison(runs)
    _print_aggregates(runs)
    return 1 if any(run.result.status is SolveStatus.FAILED for run in runs) else 0


def _command_runs(
    args: argparse.Namespace, store: ExperimentStore, runner: ExperimentRunner
) -> int:
    if args.runs_command == "list":
        rows = store.list_runs(args.limit)
        if not rows:
            print("No experiment runs recorded.")
            return 0
        print(json.dumps(rows, indent=2))
        return 0
    if args.runs_command == "show":
        print(json.dumps(store.get(args.run_id).to_dict(), indent=2, sort_keys=True))
        return 0
    run = runner.reproduce(args.run_id)
    _print_runs([run])
    print(f"reproduced_from={args.run_id}")
    if run.result.status is SolveStatus.FAILED:
        print(f"error: {run.result.errors[0]}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "problem":
            return _command_problem(args)
        store = ExperimentStore(args.db)
        runner = ExperimentRunner(store)
        if args.command == "solve":
            return _command_solve(args, runner)
        if args.command == "benchmark":
            return _command_benchmark(args, runner)
        if args.command == "suite":
            return _command_suite(args, runner)
        if args.command == "compare":
            return _command_compare(args, runner)
        return _command_runs(args, store, runner)
    except (VariaQError, FileExistsError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
