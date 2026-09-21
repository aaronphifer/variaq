"""Report artifacts: JSON, CSV, Markdown, and optional plots."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from variaq import __version__
from variaq.analysis.models import AnalysisResult
from variaq.models import utc_now

REPORT_FORMAT_VERSION = "1"


class ReportArtifact:
    """Reproducible report built from an AnalysisResult."""

    def __init__(self, report_id: str, campaign_id: str | None, analysis: AnalysisResult) -> None:
        self.report_id = report_id
        self.campaign_id = campaign_id
        self.analysis = analysis

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_format_version": REPORT_FORMAT_VERSION,
            "report_id": self.report_id,
            "campaign_id": self.campaign_id,
            "generated_at": utc_now(),
            "variaq_version": __version__,
            "source_run_ids": list(self.analysis.source_run_ids),
            "analysis": self.analysis.to_dict(),
        }


def _safe_path(directory: Path, filename: str, overwrite: bool = False) -> Path:
    target = directory / filename
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
        f"- **Generated at:** {utc_now()}",
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
