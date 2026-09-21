"""Shared application services for VariaQ integrations (web UI, CLI, future).

This module is the single orchestration boundary between presentation layers
and the authoritative VariaQ subsystems. It performs **no scientific
computation**: problems, solvers, campaigns, analysis, and reporting remain the
source of truth. All functions return plain JSON-safe dictionaries derived from
VariaQ's own serialized domain models.

Both stores use short-lived connections per call, so a long-lived service
instance is safe to share across web worker threads while a campaign writes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from variaq import __version__
from variaq.analysis.models import AnalysisQuery
from variaq.analysis.operations import analyze_runs
from variaq.analysis.reports import export_report, generate_report
from variaq.campaigns.model import DEFAULT_MAX_RUNS, ExperimentCampaign
from variaq.campaigns.plan import CampaignPlan
from variaq.campaigns.runner import CampaignRunner
from variaq.campaigns.store import CampaignStore
from variaq.capabilities import gather_capabilities
from variaq.errors import ValidationError
from variaq.experiments.runner import ExperimentRunner
from variaq.experiments.storage import ExperimentStore
from variaq.problems.base import load_problem

MAX_LIMIT = 1000


def _check_limit_offset(limit: int, offset: int) -> None:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > MAX_LIMIT:
        raise ValidationError(f"limit must be an integer between 1 and {MAX_LIMIT}")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValidationError("offset must be a non-negative integer")


class VariaQService:
    """Application facade over ExperimentStore, CampaignStore, and runners.

    The service never opens long-lived SQLite connections; every method goes
    through the stores' per-call connection context managers.
    """

    def __init__(
        self,
        db_path: Path | str,
        problems_dir: Path | str,
        reports_dir: Path | str,
    ) -> None:
        self.db_path = Path(db_path)
        self.problems_dir = Path(problems_dir)
        self.reports_dir = Path(reports_dir)
        self.store = ExperimentStore(self.db_path)
        self.campaign_store = CampaignStore(self.db_path)

    # -- capabilities / overview -------------------------------------------------

    def capabilities(self) -> dict[str, Any]:
        return gather_capabilities()

    def overview(self) -> dict[str, Any]:
        """Dashboard aggregate: counts, recents, availability. No heavy scans."""
        caps = gather_capabilities()
        solvers = {s["name"]: s for s in caps["solvers"]}
        _, run_count = self.store.query_runs(limit=1, offset=0)
        return {
            "variaq_version": __version__,
            "database_name": self.db_path.name,
            "counts": {
                "problems": len(self.list_problems(limit=MAX_LIMIT)["problems"]),
                "runs": run_count,
                "campaigns": self.campaign_store.count(),
                "reports": len(self.list_reports()["reports"]),
            },
            "recent_runs": self.list_runs(limit=5)["runs"],
            "recent_campaigns": self.campaign_store.list_campaigns(limit=5),
            "solver_availability": {
                name: {"available": s["available"], "installed": s["installed"]}
                for name, s in solvers.items()
            },
            "cudaq": next(
                (f for f in caps["frameworks"] if f["name"] == "cudaq"),
                {"installed": False, "targets": {}},
            ),
            "physical_qpu": caps["physical_qpu"],
        }

    # -- problems ----------------------------------------------------------------

    def list_problems(
        self,
        *,
        family: str | None = None,
        search: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        _check_limit_offset(limit, offset)
        metas: list[dict[str, Any]] = []
        for meta in self.store.iter_problem_summaries():
            if family is not None and meta["problem_type"] != family:
                continue
            if search:
                needle = search.lower()
                hay = f"{meta['problem_id']}"
                if needle not in hay.lower():
                    continue
            metas.append(meta)
        metas.sort(key=lambda m: m["created_at"], reverse=True)
        return {
            "total": len(metas),
            "limit": limit,
            "offset": offset,
            "problems": metas[offset : offset + limit],
        }

    def get_problem(self, problem_id: str) -> dict[str, Any]:
        definition = self.store.get_problem_definition(problem_id)
        meta = next(
            (m for m in self.store.iter_problem_summaries() if m["problem_id"] == problem_id),
            {"problem_id": problem_id, "problem_type": definition.get("problem_type")},
        )
        runs = self.list_runs(problem_id=problem_id, limit=50)
        campaigns = self.campaign_store.campaigns_for_problem(problem_id)
        exact = self.store.exact_objective(problem_id)
        return {
            "metadata": meta,
            "definition": definition,
            "family": definition.get("family", meta.get("problem_type")),
            "sense": definition.get("sense"),
            "exact_objective": exact,
            "runs": runs,
            "campaigns": campaigns,
        }

    def get_problem_file(self, problem_id: str) -> dict[str, Any]:
        """Load the canonical problem artifact from the problems dir if present."""
        candidate = self.problems_dir / f"{problem_id}.json"
        if not candidate.exists():
            raise ValidationError(
                f"No saved problem file for {problem_id!r} in {self.problems_dir.name}"
            )
        problem = load_problem(candidate)
        data = problem.to_dict()
        data["variable_count"] = problem.variable_count
        return data

    # -- runs ----------------------------------------------------------------------

    def list_runs(
        self,
        *,
        family: str | None = None,
        solver: str | None = None,
        backend: str | None = None,
        status: str | None = None,
        campaign_id: str | None = None,
        problem_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        _check_limit_offset(limit, offset)
        if status is not None and status not in {"success", "failed", "unavailable"}:
            raise ValidationError(f"Invalid status filter: {status!r}")
        campaign_members: set[str] | None = None
        if campaign_id is not None:
            # Validates the campaign exists.
            self.campaign_store.get_campaign(campaign_id)
            campaign_members = set(self.campaign_store.get_run_ids(campaign_id))
        rows, total = self.store.query_runs(
            problem_type=family,
            solver_name=solver,
            backend_name=backend,
            status=status,
            problem_id=problem_id,
            run_ids=campaign_members,
            limit=limit,
            offset=offset,
        )
        for row in rows:
            row["in_campaign"] = bool(
                campaign_members is not None and row["run_id"] in campaign_members
            )
        return {"total": total, "limit": limit, "offset": offset, "runs": rows}

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get(run_id)
        campaigns = self.campaign_store.campaigns_for_run(run_id)
        data = run.to_dict()
        data["campaigns"] = campaigns
        data["rerun_of"] = run.rerun_of
        return data

    # -- campaigns -----------------------------------------------------------------

    def list_campaigns(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        _check_limit_offset(limit, offset)
        # CampaignStore.list_campaigns is newest-first and limit-bounded; we
        # paginate by fetching a larger window when an offset is requested.
        rows = self.campaign_store.list_campaigns(limit=MAX_LIMIT)
        decorated = []
        for row in rows:
            member_rows = self.campaign_store.get_runs_with_status(row["campaign_id"])
            statuses: dict[str, int] = {}
            for member in member_rows:
                statuses[member["status"]] = statuses.get(member["status"], 0) + 1
            definition = self.campaign_store.get_campaign(row["campaign_id"])
            decorated.append(
                {
                    **row,
                    "requested_runs": definition.requested_runs,
                    "completed_runs": len(member_rows),
                    "status_counts": statuses,
                }
            )
        return {
            "total": len(decorated),
            "limit": limit,
            "offset": offset,
            "campaigns": decorated[offset : offset + limit],
        }

    def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        campaign = self.campaign_store.get_campaign(campaign_id)
        members = self.campaign_store.get_runs_with_status(campaign_id)
        statuses: dict[str, int] = {}
        solvers: dict[str, int] = {}
        for member in members:
            statuses[member["status"]] = statuses.get(member["status"], 0) + 1
            solvers[member["solver_name"]] = solvers.get(member["solver_name"], 0) + 1
        return {
            "definition": campaign.to_dict(),
            "campaign_id": campaign_id,
            "requested_runs": campaign.requested_runs,
            "completed_runs": len(members),
            "status_counts": statuses,
            "solver_breakdown": solvers,
            "runs": members,
        }

    def plan_campaign(self, definition: dict[str, Any]) -> dict[str, Any]:
        campaign = ExperimentCampaign.from_dict(definition)
        plan = CampaignPlan(campaign).build()
        plan["definition"] = campaign.to_dict()
        return plan

    def run_campaign(
        self,
        definition: dict[str, Any],
        *,
        override_max_runs: bool = False,
        max_runs: int = DEFAULT_MAX_RUNS,
        on_run_recorded: Any | None = None,
        should_abort: Any | None = None,
    ) -> dict[str, Any]:
        """Execute a campaign. Must be called from a worker thread by the web app."""
        campaign = ExperimentCampaign.from_dict(definition)
        runner = ExperimentRunner(self.store)
        campaign_runner = CampaignRunner(
            runner,
            self.campaign_store,
            self.problems_dir,
            max_runs=max_runs,
        )
        return campaign_runner.run(
            campaign,
            override_max_runs=override_max_runs,
            on_run_recorded=on_run_recorded,
            should_abort=should_abort,
        )

    # -- analysis ------------------------------------------------------------------

    def analyze(
        self,
        *,
        campaign_id: str | None = None,
        run_ids: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        group_by: list[str] | None = None,
        scaling_x: str = "problem_size",
        include_failed: bool = False,
        include_unavailable: bool = False,
        comparisons: list[str] | None = None,
    ) -> dict[str, Any]:
        if campaign_id is not None:
            selected = self.campaign_store.get_run_ids(campaign_id)
        elif run_ids:
            selected = list(run_ids)
        else:
            raise ValidationError("Analysis requires a campaign_id or a non-empty run_ids list")
        if not selected:
            raise ValidationError("No runs selected for analysis")
        runs = [self.store.get(rid) for rid in selected]
        query = AnalysisQuery(
            campaign_id=campaign_id,
            run_ids=tuple(selected),
            filters=dict(filters or {}),
            group_by=tuple(group_by or ()),
            include_failed=include_failed,
            include_unavailable=include_unavailable,
        )
        result = analyze_runs(
            runs,
            query,
            scaling_x_metric=scaling_x,
            comparisons=tuple(comparisons or ()),
        )
        return result.to_dict()

    # -- reports -------------------------------------------------------------------

    def list_reports(self) -> dict[str, Any]:
        """Enumerate report metadata from JSON artifacts in the reports root."""
        reports: list[dict[str, Any]] = []
        root = self.reports_dir
        if root.exists():
            for path in sorted(root.rglob("*.json")):
                report = self._read_report_meta(path, root)
                if report is not None:
                    reports.append(report)
        reports.sort(key=lambda r: (r.get("generated_at") or "", r["report_id"]), reverse=True)
        return {"total": len(reports), "reports": reports}

    def _read_report_meta(self, path: Path, root: Path) -> dict[str, Any] | None:
        if not self._is_within_root(path, root):
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict) or "report_id" not in data:
            return None
        rid = str(data["report_id"])
        files = self._report_files(rid, path.parent, root)
        warnings: list[str] = []
        if data.get("analysis", {}).get("warnings"):
            warnings = [str(w) for w in data["analysis"]["warnings"]]
        return {
            "report_id": rid,
            "campaign_id": data.get("campaign_id"),
            "generated_at": data.get("generated_at"),
            "variaq_version": data.get("variaq_version"),
            "report_format_version": data.get("report_format_version"),
            "source_run_count": len(data.get("source_run_ids", []) or []),
            "formats": sorted({f["format"] for f in files}),
            "files": files,
            "warnings": warnings,
            "directory": str(path.parent.relative_to(root)),
        }

    def _report_files(self, report_id: str, directory: Path, root: Path) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        if not directory.is_dir() or not self._is_within_root(directory, root):
            return files
        for path in sorted(directory.iterdir()):
            fmt = self._report_file_format(report_id, path.name)
            if not path.is_file() or fmt is None or not self._is_within_root(path, root):
                continue
            files.append(
                {
                    "name": path.name,
                    "format": fmt,
                    "size": path.stat().st_size,
                    "path": str(path.relative_to(root)),
                }
            )
        return files

    @staticmethod
    def _report_file_format(report_id: str, name: str) -> str | None:
        """Return the format for an artifact filename VariaQ itself can emit."""
        suffixes = {
            ".json": "json",
            ".md": "markdown",
            "_groups.csv": "csv",
            "_scaling.csv": "csv",
            "_scaling.png": "plot",
        }
        for suffix, report_format in suffixes.items():
            if name == f"{report_id}{suffix}":
                return report_format
        return None

    @staticmethod
    def _is_within_root(path: Path, root: Path) -> bool:
        """Reject paths (including symlinks) whose resolved target leaves root."""
        try:
            resolved = path.resolve()
            root_resolved = root.resolve()
        except OSError:
            return False
        return resolved == root_resolved or root_resolved in resolved.parents

    def get_report(self, report_id: str) -> dict[str, Any]:
        path, root = self.find_report_source(report_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        files = self._report_files(str(data["report_id"]), path.parent, root)
        return {
            "report": data,
            "files": files,
            "directory": str(path.parent.relative_to(root)),
        }

    def find_report_source(self, report_id: str) -> tuple[Path, Path]:
        """Locate the canonical JSON for a report ID, rejecting malformed IDs."""
        if not report_id or "/" in report_id or "\\" in report_id or ".." in report_id:
            raise ValidationError(f"Invalid report id: {report_id!r}")
        root = self.reports_dir
        if root.exists():
            for path in sorted(root.rglob("*.json")):
                if not self._is_within_root(path, root):
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if isinstance(data, dict) and data.get("report_id") == report_id:
                    return path, root
        raise ValidationError(f"Report not found: {report_id}")

    def get_report_file_path(self, report_id: str, filename: str) -> Path:
        """Resolve a report-owned file within the reports root (traversal-safe)."""
        source, root = self.find_report_source(report_id)
        directory = source.parent
        if not filename or "/" in filename or "\\" in filename:
            raise ValidationError(f"Invalid report filename: {filename!r}")
        if self._report_file_format(str(report_id), filename) is None:
            raise ValidationError("Requested file is not a known VariaQ report artifact")
        target = (directory / filename).resolve()
        if not self._is_within_root(target, root):
            raise ValidationError("Requested file escapes the report directory")
        if not target.exists() or not target.is_file():
            raise ValidationError(f"Report file not found: {filename}")
        return target

    def create_report(
        self,
        campaign_id: str,
        *,
        formats: list[str] | None = None,
        group_by: list[str] | None = None,
        scaling_x: str = "problem_size",
        comparisons: list[str] | None = None,
        plots: bool = False,
        overwrite: bool = False,
        output_subdir: str = "",
    ) -> dict[str, Any]:
        run_ids = self.campaign_store.get_run_ids(campaign_id)
        if not run_ids:
            raise ValidationError(f"Campaign {campaign_id!r} has no runs")
        runs = [self.store.get(rid) for rid in run_ids]
        query = AnalysisQuery(
            campaign_id=campaign_id,
            run_ids=tuple(run_ids),
            group_by=tuple(group_by or ("problem_id", "solver")),
            include_failed=True,
        )
        analysis = analyze_runs(
            runs,
            query,
            scaling_x_metric=scaling_x,
            comparisons=tuple(comparisons or ()),
        )
        report = generate_report(analysis, campaign_id=campaign_id)
        selected = tuple(formats) if formats else ("json", "csv", "markdown")
        allowed = {"json", "csv", "markdown"}
        unknown = set(selected) - allowed
        if unknown:
            raise ValidationError(f"Unknown report formats: {sorted(unknown)}")
        if plots:
            selected = (*selected, "plots")
        target = self.reports_dir
        if output_subdir:
            if output_subdir.startswith(("/", "\\")) or ".." in Path(output_subdir).parts:
                raise ValidationError(f"Invalid report output subdirectory: {output_subdir!r}")
            target = (self.reports_dir / output_subdir).resolve()
            root = self.reports_dir.resolve()
            if root != target and root not in target.parents:
                raise ValidationError("Report output directory escapes the reports root")
        warnings: list[str] = []
        try:
            paths = export_report(report, target, formats=selected, overwrite=overwrite)
        except ImportError as exc:
            # Plots requested without matplotlib: export the core formats.
            core = tuple(f for f in selected if f not in {"plots", "plot"})
            if not core:
                raise ValidationError(f"Plotting unavailable: {exc}") from exc
            paths = export_report(report, target, formats=core, overwrite=overwrite)
            warnings.append(f"Plotting skipped: {exc}")
        return {"report_id": report.report_id, "paths": paths, "warnings": warnings}
