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
                if existing_definition != campaign.to_dict():
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

    def list_campaigns(self, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise ValidationError("Campaign list limit must be between 1 and 1000")
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT campaign_id, name, family, created_at FROM campaigns "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (limit,),
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

    def get_runs_with_status(self, campaign_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT run_id, status, solver_name, problem_id, created_at "
                "FROM campaign_runs WHERE campaign_id = ? ORDER BY created_at",
                (campaign_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def count(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0])
