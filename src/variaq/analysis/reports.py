"""Report artifacts: JSON, CSV, Markdown, and optional plots."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from variaq import __version__
from variaq.analysis.models import AnalysisResult
from variaq.errors import ValidationError
from variaq.models import utc_now

REPORT_FORMAT_VERSION = "1"


class ReportArtifact:
    """Reproducible report built from an AnalysisResult."""

    def __init__(self, report_id: str, campaign_id: str | None, analysis: AnalysisResult) -> None:
        self.report_id = report_id
        self.campaign_id = campaign_id
        self.analysis = analysis
        self.generated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_format_version": REPORT_FORMAT_VERSION,
            "report_id": self.report_id,
            "campaign_id": self.campaign_id,
            "generated_at": self.generated_at,
            "variaq_version": __version__,
            "source_run_ids": list(self.analysis.source_run_ids),
            "analysis": self.analysis.to_dict(),
        }


def _safe_path(directory: Path, filename: str, overwrite: bool = False) -> Path:
    target = directory / filename
    if (
        Path(filename).name != filename
        or "/" in filename
        or "\\" in filename
        or target.is_symlink()
        or target.resolve().parent != directory.resolve()
    ):
        raise ValidationError("Requested file is outside the report root or is a symlink")
    if target.exists() and not overwrite:
        raise FileExistsError(f"Report file exists: {target}; use --overwrite to replace")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def write_json_report(report: ReportArtifact, directory: Path, *, overwrite: bool = False) -> Path:
    path = _safe_path(directory, f"{report.report_id}.json", overwrite)
    path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _group_rows(groups: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in groups:
        row: dict[str, Any] = {}
        row.update(group["group_key"])
        row["count"] = group["count"]
        q = group["quality"]
        row["best_objective"] = q["best_objective"]
        row["mean_objective"] = q["mean_objective"]
        row["mean_gap_percent"] = q["mean_gap_percent"]
        row["success_at_optimum_rate"] = q["success_at_optimum_rate"]
        row["feasible_runs"] = group["feasibility"]["feasible_runs"]
        row["infeasible_runs"] = group["feasibility"]["infeasible_runs"]
        row["mean_feasible_rate"] = group["feasibility"]["mean_feasible_rate"]
        row["wall_time_mean"] = group["timing"]["total_wall_time_seconds"]["mean"]
        rows.append(row)
    return rows


def _flat_row(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Keep nested scalar metrics useful in CSV; retain lists as lossless JSON."""
    row: dict[str, Any] = {}
    for key, item in value.items():
        name = f"{prefix}{key}"
        if isinstance(item, dict) and item:
            row.update(_flat_row(item, name + "."))
        elif isinstance(item, (dict, list, tuple)):
            row[name] = json.dumps(item, sort_keys=True)
        else:
            row[name] = item
    return row


def _write_rows(path: Path, rows: list[dict[str, Any]], empty_fields: list[str]) -> None:
    fields = sorted({key for row in rows for key in row}) or empty_fields
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_csv_report(
    report: ReportArtifact, directory: Path, *, overwrite: bool = False
) -> dict[str, Path]:
    result: dict[str, Path] = {}
    analysis = report.analysis.to_dict()

    group_path = _safe_path(directory, f"{report.report_id}_groups.csv", overwrite)
    rows = _group_rows(analysis["groups"])
    if rows:
        with group_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        result["groups"] = group_path

    if analysis["scaling_points"]:
        scaling_path = _safe_path(directory, f"{report.report_id}_scaling.csv", overwrite)
        srows: list[dict[str, Any]] = []
        for point in analysis["scaling_points"]:
            row = {"x_metric": point["x_metric"], "x_value": point["x_value"]}
            row.update(point["group_key"])
            row["count"] = point["count"]
            row["best_objective"] = point["quality"]["best_objective"]
            row["mean_gap_percent"] = point["quality"]["mean_gap_percent"]
            row["mean_feasible_rate"] = point["feasibility"]["mean_feasible_rate"]
            row["wall_time_mean"] = point["timing"]["total_wall_time_seconds"]["mean"]
            srows.append(row)
        with scaling_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(srows[0].keys()))
            writer.writeheader()
            writer.writerows(srows)
        result["scaling"] = scaling_path

    if any(c["comparison_type"] == "paired_solvers" for c in analysis["comparisons"]):
        run_rows = [_flat_row(r) for i in analysis["instances"] for r in i["runs"]]
        pair_rows = [
            _flat_row(p)
            for c in analysis["comparisons"]
            if c["comparison_type"] == "paired_solvers"
            for p in c["pairs"]
        ]
        repeat_rows = [
            _flat_row({"problem_id": i["problem_id"], **r})
            for i in analysis["instances"]
            for r in i["repeats"]
        ]
        for name, records, fields in (
            ("runs", run_rows, ["run_id", "problem_id", "objective"]),
            ("pairs", pair_rows, ["problem_id", "left_run_id", "right_run_id"]),
            ("repeats", repeat_rows, ["problem_id", "solver", "warmup_mode"]),
        ):
            target = _safe_path(directory, f"{report.report_id}_{name}.csv", overwrite)
            _write_rows(target, records, fields)
            result[name] = target
    return result


def write_markdown_report(
    report: ReportArtifact, directory: Path, *, overwrite: bool = False
) -> Path:
    path = _safe_path(directory, f"{report.report_id}.md", overwrite)
    analysis = report.analysis.to_dict()
    lines: list[str] = [
        f"# VariaQ Campaign Report: {report.report_id}",
        "",
        f"- **VariaQ version:** {__version__}",
        f"- **Report format version:** {REPORT_FORMAT_VERSION}",
        f"- **Generated at:** {report.generated_at}",
    ]
    if report.campaign_id:
        lines.append(f"- **Campaign ID:** {report.campaign_id}")
    lines.append(f"- **Source run count:** {len(analysis['source_run_ids'])}")
    lines.append("")
    lines.append("## Source run IDs")
    lines.append("")
    for run_id in analysis["source_run_ids"]:
        lines.append(f"- `{run_id}`")
    lines.append("")

    lines.append("## Group summaries")
    lines.append("")
    if not analysis["groups"]:
        lines.append("No groups produced.")
    else:
        header = "| group | count | best | mean gap % | feasible rate | wall mean s |"
        lines.append(header)
        lines.append("|" + "|".join(["---"] * 6) + "|")
        for group in analysis["groups"]:
            key = ", ".join(f"{k}={v}" for k, v in group["group_key"].items())
            q = group["quality"]
            f = group["feasibility"]
            t = group["timing"]["total_wall_time_seconds"]
            lines.append(
                f"| {key} | {group['count']} | {q['best_objective']} | "
                f"{q['mean_gap_percent']} | {f['mean_feasible_rate']} | {t['mean']} |"
            )
    lines.append("")

    if analysis["scaling_points"]:
        lines.append("## Scaling summary")
        lines.append("")
        lines.append("| x | group | count | best | wall mean s |")
        lines.append("|" + "|".join(["---"] * 5) + "|")
        for point in analysis["scaling_points"]:
            key = ", ".join(f"{k}={v}" for k, v in point["group_key"].items())
            q = point["quality"]
            t = point["timing"]["total_wall_time_seconds"]
            lines.append(
                f"| {point['x_metric']}={point['x_value']} | {key} | {point['count']} | "
                f"{q['best_objective']} | {t['mean']} |"
            )
        lines.append("")

    if analysis["instances"]:
        lines.extend(
            [
                "## Paired per-instance analysis",
                "",
                "Objectives are re-evaluated by the original problem. Gaps require an exact",
                "reference in the selected runs. Null means unavailable; CSV/JSON carry reasons.",
                "Unwarmed runs do not establish a fresh GPU context. Simulator timings do not",
                "demonstrate quantum advantage. Solver compute scopes may differ from wall time.",
                "",
                "| problem | run | solver | status | objective | gap % | feasible | wall s | "
                "compute s | init s | warmup s | mode |",
                "|" + "|".join(["---"] * 12) + "|",
            ]
        )
        missing_notes: list[str] = []
        for instance in analysis["instances"]:
            for r in instance["runs"]:
                t = r["timing"]
                values = [
                    instance["problem_id"],
                    r["run_id"],
                    r["solver"],
                    r["status"],
                    r["objective"],
                    r["optimality_gap_percent"],
                    r["feasible"],
                    t["wall_time_seconds"],
                    t["solver_time_seconds"],
                    t["initialization_seconds"],
                    t["warmup_seconds"],
                    r["warmup_mode"],
                ]
                lines.append(
                    "| " + " | ".join("null" if v is None else str(v) for v in values) + " |"
                )
                if r["missing_measurements"]:
                    reasons = "; ".join(f"{k}: {v}" for k, v in r["missing_measurements"].items())
                    missing_notes.append(f"- `{r['run_id']}`: {reasons}")
        lines.extend(["", "Missing measurement reasons:", "", *missing_notes])
        lines.extend(
            [
                "",
                "## Repeat variability",
                "",
                "Sample standard deviation is null with fewer than two observations.",
                "",
                "| problem | solver | mode | objective n | objective mean | objective std | "
                "wall n | wall mean s | wall std s |",
                "|" + "|".join(["---"] * 9) + "|",
            ]
        )
        for instance in analysis["instances"]:
            for r in instance["repeats"]:
                o, t = r["objective"], r["timing"]["wall_time_seconds"]
                values = [
                    instance["problem_id"],
                    r["solver"],
                    r["warmup_mode"],
                    o["count"],
                    o["mean"],
                    o["std"],
                    t["count"],
                    t["mean"],
                    t["std"],
                ]
                lines.append(
                    "| " + " | ".join("null" if v is None else str(v) for v in values) + " |"
                )
        lines.append("")
    for comparison in analysis["comparisons"]:
        if comparison["comparison_type"] != "paired_solvers":
            continue
        lines.extend(
            [
                "## Paired solver observations",
                "",
                "Positive objective improvement favors the left solver for either objective sense.",
                "",
                "| problem | repeat | left run | right run | objective improvement left | "
                "max expectation delta | reason |",
                "|" + "|".join(["---"] * 7) + "|",
            ]
        )
        for p in comparison["pairs"]:
            n = p["numerical_correctness"]
            values = [
                p["problem_id"],
                p["repeat_key"],
                p["left_run_id"],
                p["right_run_id"],
                p["objective_improvement_left"],
                n["max_expectation_delta"],
                n["reason"] or p["missing_pairs"] or "matched expectations",
            ]
            lines.append("| " + " | ".join("null" if v is None else str(v) for v in values) + " |")
        lines.append("")

    if analysis["warnings"]:
        lines.append("## Warnings")
        lines.append("")
        for warning in analysis["warnings"]:
            lines.append(f"- {warning}")
        lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_plots(
    report: ReportArtifact,
    directory: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Generate optional plots if matplotlib is available."""
    result: dict[str, Path] = {}
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError("Plotting requires matplotlib. Install it or skip plots.") from exc

    analysis = report.analysis.to_dict()
    scaling = analysis["scaling_points"]
    if scaling:
        fig, ax = plt.subplots()
        by_group: dict[str, list[tuple[float, float]]] = {}
        for point in scaling:
            key = ", ".join(f"{k}={v}" for k, v in point["group_key"].items())
            by_group.setdefault(key, []).append(
                (point["x_value"], point["quality"]["best_objective"])
            )
        for key, points in sorted(by_group.items()):
            xs, ys = zip(*sorted(points), strict=False)
            ax.plot(xs, ys, marker="o", label=key)
        ax.set_xlabel(analysis["scaling_points"][0]["x_metric"])
        ax.set_ylabel("best objective")
        ax.set_title("Scaling: objective vs problem size")
        ax.legend()
        plot_path = _safe_path(directory, f"{report.report_id}_scaling.png", overwrite)
        fig.savefig(plot_path)
        plt.close(fig)
        result["scaling_objective"] = plot_path
    return result


def generate_report(
    analysis: AnalysisResult,
    *,
    campaign_id: str | None = None,
    report_id: str | None = None,
) -> ReportArtifact:
    """Create a deterministic report ID from source runs and query when not supplied."""
    if report_id is None:
        canonical = {
            "campaign_id": campaign_id,
            "query": analysis.query.to_dict(),
            "source_run_ids": sorted(analysis.source_run_ids),
            "analysis": analysis.to_dict(),
        }
        import hashlib

        digest = hashlib.sha256(
            json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()[:16]
        report_id = f"report-{digest}"
    return ReportArtifact(report_id=report_id, campaign_id=campaign_id, analysis=analysis)


def export_report(
    report: ReportArtifact,
    directory: Path,
    *,
    formats: tuple[str, ...] = ("json", "csv", "markdown"),
    overwrite: bool = False,
) -> dict[str, Any]:
    """Export report in requested formats. Plots are optional and requested separately."""
    paths: dict[str, Any] = {}
    if "json" in formats:
        paths["json"] = str(write_json_report(report, directory, overwrite=overwrite))
    if "csv" in formats:
        paths["csv"] = {
            k: str(v) for k, v in write_csv_report(report, directory, overwrite=overwrite).items()
        }
    if "markdown" in formats:
        paths["markdown"] = str(write_markdown_report(report, directory, overwrite=overwrite))
    if "plots" in formats or "plot" in formats:
        try:
            plot_paths = write_plots(report, directory, overwrite=overwrite)
            if plot_paths:
                paths["plots"] = {k: str(v) for k, v in plot_paths.items()}
        except ImportError as exc:
            if not any(f in formats for f in ("json", "csv", "markdown")):
                raise
            paths.setdefault("warnings", []).append(str(exc))
    return paths
