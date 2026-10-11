"""Durable web task snapshots with one OS-owned local worker slot."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from variaq.campaigns.store import CampaignStore
from variaq.models import utc_now


class TaskJournal:
    def __init__(self, store: CampaignStore) -> None:
        self.store = store
        self._worker_file = None
        lock_path = Path(str(store.path.resolve()) + ".web-worker.lock")
        worker_file = lock_path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                worker_file.seek(0, 2)
                if worker_file.tell() == 0:
                    worker_file.write(b"0")
                    worker_file.flush()
                worker_file.seek(0)
                msvcrt.locking(worker_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(worker_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            worker_file.close()
        else:
            self._worker_file = worker_file
        with store._connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS web_tasks ("
                "task_id TEXT PRIMARY KEY, request_key TEXT UNIQUE, record_json TEXT NOT NULL)"
            )
        if self.can_execute:
            self.reconcile()

    @property
    def can_execute(self) -> bool:
        return self._worker_file is not None

    def close(self) -> None:
        if self._worker_file is not None:
            self._worker_file.close()
            self._worker_file = None

    def __del__(self) -> None:
        self.close()

    def save(self, task: dict[str, Any], request_key: str | None = None) -> None:
        with self.store._connection() as connection:
            connection.execute(
                "INSERT INTO web_tasks(task_id, request_key, record_json) VALUES (?, ?, ?) "
                "ON CONFLICT(task_id) DO UPDATE SET record_json=excluded.record_json",
                (task["task_id"], request_key, json.dumps(task)),
            )

    def get(self, *, task_id: str | None = None, request_key: str | None = None) -> dict | None:
        key, value = ("task_id", task_id) if task_id else ("request_key", request_key)
        with self.store._connection() as connection:
            row = connection.execute(
                f"SELECT record_json FROM web_tasks WHERE {key}=?", (value,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def current(self) -> dict | None:
        with self.store._connection() as connection:
            row = connection.execute(
                "SELECT record_json FROM web_tasks ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        return json.loads(row[0]) if row else None

    def reconcile(self) -> None:
        # Called only while owning the OS worker lock: no other web worker can
        # still be executing. A killed process releases this lock automatically.
        with self.store._connection() as connection:
            rows = connection.execute(
                "SELECT r.run_id, r.status, r.solver_name, r.problem_id, r.created_at, "
                "r.record_json FROM runs r LEFT JOIN campaign_runs c ON c.run_id=r.run_id "
                "WHERE c.run_id IS NULL"
            ).fetchall()
            for row in rows:
                campaign_id = (
                    json.loads(row["record_json"]).get("environment", {}).get("campaign_id")
                )
                if (
                    campaign_id
                    and connection.execute(
                        "SELECT 1 FROM campaigns WHERE campaign_id=?", (campaign_id,)
                    ).fetchone()
                ):
                    connection.execute(
                        "INSERT INTO campaign_runs VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            campaign_id,
                            row["run_id"],
                            row["status"],
                            row["solver_name"],
                            row["problem_id"],
                            row["created_at"],
                        ),
                    )
            tasks = connection.execute("SELECT record_json FROM web_tasks").fetchall()
            records = [json.loads(r[0]) for r in connection.execute("SELECT record_json FROM runs")]
            for row in tasks:
                task = json.loads(row[0])
                matching = [
                    r
                    for r in records
                    if r.get("environment", {}).get("web_task_id") == task["task_id"]
                ]
                task["completed_runs"] = len(matching)
                if task.get("source_run_id") and matching:
                    task["result"] = matching[0]
                if task["status"] in {"starting", "running"}:
                    task["status"] = "interrupted"
                    task["finished_at"] = utc_now()
                    task["error"] = {
                        "type": "Interrupted",
                        "message": "The server stopped before recording a final task state. "
                        "Completed "
                        "records are preserved. Remaining work was not retried; an in-flight "
                        "result may not have been saved. Inspect the campaign before explicitly "
                        "planning a new campaign with a different name.",
                    }
                connection.execute(
                    "UPDATE web_tasks SET record_json=? WHERE task_id=?",
                    (json.dumps(task), task["task_id"]),
                )
