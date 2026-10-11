"""Campaign persistence: additive SQLite tables, no migration of existing runs."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from variaq.campaigns.model import ExperimentCampaign, campaign_definition_id
from variaq.errors import DuplicateRunError, ValidationError


class CampaignStore:
    """Minimal append-only campaign membership store backed by SQLite.

    Campaign definitions and run associations are stored in separate tables.
    Existing run records in the ``runs`` table remain authoritative; this
    store only records membership.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS campaigns (
                    campaign_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    family TEXT NOT NULL,
                    definition_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS campaign_runs (
                    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    solver_name TEXT NOT NULL,
                    problem_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_campaign_runs_campaign
                    ON campaign_runs(campaign_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_campaign_runs_run
                    ON campaign_runs(run_id);
                """
            )

    def save_campaign(self, campaign: ExperimentCampaign) -> str:
        campaign_id = campaign_definition_id(campaign)
        definition = json.dumps(campaign.to_dict(), separators=(",", ":"), sort_keys=True)
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT definition_json FROM campaigns WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()
            if existing is not None:
                existing_definition = json.loads(existing["definition_json"])
                incoming_definition = campaign.to_dict()
                # Creation time is not part of deterministic campaign identity.
                # Preserve the original definition while appending new executions.
                existing_definition.pop("created_at", None)
                incoming_definition.pop("created_at", None)
                if existing_definition != incoming_definition:
                    raise DuplicateRunError(
                        f"Campaign ID {campaign_id} already exists with different content"
                    )
                return campaign_id
            connection.execute(
                "INSERT INTO campaigns(campaign_id, name, family, definition_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (campaign_id, campaign.name, campaign.family, definition, campaign.created_at),
            )
        return campaign_id

    def get_campaign(self, campaign_id: str) -> ExperimentCampaign:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT definition_json FROM campaigns WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()
        if row is None:
            raise ValidationError(f"Campaign not found: {campaign_id}")
        return ExperimentCampaign.from_dict(json.loads(row["definition_json"]))

    def list_campaigns(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise ValidationError("Campaign list limit must be between 1 and 1000")
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT campaign_id, name, family, created_at FROM campaigns "
                "ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_run(
        self,
        campaign_id: str,
        run_id: str,
        status: str,
        solver_name: str,
        problem_id: str,
        created_at: str,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO campaign_runs(
                    campaign_id, run_id, status, solver_name, problem_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (campaign_id, run_id, status, solver_name, problem_id, created_at),
            )

    def get_run_ids(self, campaign_id: str) -> list[str]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT run_id FROM campaign_runs WHERE campaign_id = ? ORDER BY created_at",
                (campaign_id,),
            ).fetchall()
        return [row["run_id"] for row in rows]

    def get_runs_with_status(
        self, campaign_id: str, *, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        with self._connection() as connection:
            suffix = " LIMIT ? OFFSET ?" if limit is not None else ""
            parameters = (campaign_id, limit, offset) if limit is not None else (campaign_id,)
            rows = connection.execute(
                "SELECT run_id, status, solver_name, problem_id, created_at "
                "FROM campaign_runs WHERE campaign_id = ? ORDER BY created_at" + suffix,
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def run_statistics(self, campaign_id: str) -> dict[str, Any]:
        """Aggregate membership without loading every run into presentation memory."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT status, solver_name, COUNT(*) AS n FROM campaign_runs "
                "WHERE campaign_id = ? GROUP BY status, solver_name",
                (campaign_id,),
            ).fetchall()
        statuses: dict[str, int] = {}
        solvers: dict[str, int] = {}
        for row in rows:
            statuses[row["status"]] = statuses.get(row["status"], 0) + row["n"]
            solvers[row["solver_name"]] = solvers.get(row["solver_name"], 0) + row["n"]
        return {
            "completed_runs": sum(statuses.values()),
            "status_counts": statuses,
            "solver_breakdown": solvers,
        }

    def campaigns_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT c.campaign_id, c.name, c.family, c.created_at
                FROM campaigns c JOIN campaign_runs cr ON cr.campaign_id = c.campaign_id
                WHERE cr.run_id = ? ORDER BY c.created_at DESC
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def campaigns_for_problem(self, problem_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT c.campaign_id, c.name, c.family, c.created_at
                FROM campaigns c JOIN campaign_runs cr ON cr.campaign_id = c.campaign_id
                WHERE cr.problem_id = ? ORDER BY c.created_at DESC
                """,
                (problem_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def count(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0])

    def fully_recorded_count(self) -> int:
        """Membership coverage, not a claim of successful or recoverable execution."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT c.definition_json, COUNT(cr.run_id) AS recorded FROM campaigns c "
                "LEFT JOIN campaign_runs cr ON cr.campaign_id = c.campaign_id "
                "GROUP BY c.campaign_id"
            ).fetchall()
        return sum(
            row["recorded"]
            >= ExperimentCampaign.from_dict(json.loads(row["definition_json"])).requested_runs
            for row in rows
        )
