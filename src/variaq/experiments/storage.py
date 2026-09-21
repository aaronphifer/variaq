from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from variaq.errors import DuplicateRunError, ValidationError
from variaq.models import ExperimentRun
from variaq.problems.base import problem_from_dict


def _problem_size_hint(problem_type: str, definition: dict[str, Any]) -> dict[str, Any]:
    """Extract a small, family-aware size descriptor from a stored definition."""

    def _count(primary: Any, scalar: Any) -> Any:
        if isinstance(primary, list):
            return len(primary)
        if primary is not None:
            return primary
        return scalar

    if problem_type == "maxcut" or problem_type == "graph-partition":
        nodes = _count(definition.get("node_ids"), definition.get("node_count"))
        edges = definition.get("edges") or []
        hint: dict[str, Any] = {
            "nodes": nodes,
            "edges": len(edges) if isinstance(edges, list) else edges,
        }
        if problem_type == "graph-partition" and definition.get("partition_count"):
            hint["partitions"] = definition["partition_count"]
        return hint
    if problem_type == "assignment":
        tasks = _count(definition.get("task_ids"), definition.get("task_count"))
        resources = _count(definition.get("resource_ids"), definition.get("resource_count"))
        return {"tasks": tasks, "resources": resources}
    if problem_type == "subset-selection":
        candidates = _count(definition.get("candidate_ids"), definition.get("candidate_count"))
        return {"candidates": candidates}
    return {}


class ExperimentStore:
    """Append-only experiment records backed by local SQLite."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Own one transactional connection and always release its file handle."""
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
                CREATE TABLE IF NOT EXISTS schema_info (
                    version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS problems (
                    problem_id TEXT PRIMARY KEY,
                    problem_type TEXT NOT NULL,
                    definition_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    benchmark_id TEXT,
                    created_at TEXT NOT NULL,
                    problem_id TEXT NOT NULL REFERENCES problems(problem_id),
                    problem_type TEXT NOT NULL,
                    solver_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    objective REAL,
                    feasible INTEGER NOT NULL,
                    wall_time_seconds REAL NOT NULL,
                    backend_type TEXT NOT NULL,
                    backend_name TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    record_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_runs_problem ON runs(problem_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_runs_benchmark ON runs(benchmark_id, created_at);
                """
            )
            row = connection.execute("SELECT version FROM schema_info LIMIT 1").fetchone()
            if row is None:
                connection.execute("INSERT INTO schema_info(version) VALUES (1)")
            elif row["version"] != 1:
                raise ValidationError(f"Unsupported experiment database schema: {row['version']}")

    def save(self, run: ExperimentRun) -> None:
        problem = problem_from_dict(run.problem)
        if (
            problem.problem_id != run.result.problem_id
            or problem.problem_type != run.result.problem_type
        ):
            raise ValidationError("Run result does not match its embedded problem snapshot")
        definition = json.dumps(run.problem, separators=(",", ":"), sort_keys=True)
        record = json.dumps(run.to_dict(), separators=(",", ":"), sort_keys=True)
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT definition_json FROM problems WHERE problem_id = ?",
                (run.result.problem_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO problems(problem_id, problem_type, definition_json, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        run.result.problem_id,
                        run.result.problem_type,
                        definition,
                        run.created_at,
                    ),
                )
            else:
                existing_problem = problem_from_dict(json.loads(existing["definition_json"]))
                if existing_problem.identity_payload() != problem.identity_payload():
                    raise ValidationError(
                        f"Problem ID collision or mutation detected for {run.result.problem_id}"
                    )
            try:
                connection.execute(
                    """
                    INSERT INTO runs(
                        run_id, benchmark_id, created_at, problem_id, problem_type,
                        solver_name, status, objective, feasible, wall_time_seconds,
                        backend_type, backend_name, seed, record_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id,
                        run.benchmark_id,
                        run.created_at,
                        run.result.problem_id,
                        run.result.problem_type,
                        run.result.solver_name,
                        run.result.status.value,
                        run.result.objective,
                        int(run.result.feasible),
                        run.result.wall_time_seconds,
                        run.result.backend.backend_type,
                        run.result.backend.name,
                        run.result.seed,
                        record,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if "runs.run_id" in str(exc) or "UNIQUE constraint failed: runs.run_id" in str(exc):
                    raise DuplicateRunError(
                        f"Run {run.run_id} already exists; existing records are never overwritten"
                    ) from exc
                raise

    def get(self, run_id: str) -> ExperimentRun:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT record_json FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise ValidationError(f"Run not found: {run_id}")
        return ExperimentRun.from_dict(json.loads(row["record_json"]))

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise ValidationError("Run list limit must be between 1 and 1000")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT run_id, benchmark_id, created_at, problem_id, solver_name,
                       status, objective, feasible, wall_time_seconds,
                       backend_type, backend_name, seed
                FROM runs ORDER BY created_at DESC, rowid DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def query_runs(
        self,
        *,
        problem_type: str | None = None,
        solver_name: str | None = None,
        backend_name: str | None = None,
        status: str | None = None,
        problem_id: str | None = None,
        run_ids: set[str] | frozenset[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Filtered, paginated run listing. Returns (rows, total_matching).

        Read-only; used by presentation layers. When ``run_ids`` is provided,
        results are restricted to that membership set (SQL ``IN`` over bound
        parameters, never interpolated into the statement text).
        """
        if limit < 1 or limit > 1000:
            raise ValidationError("Run list limit must be between 1 and 1000")
        if offset < 0:
            raise ValidationError("Run list offset must be non-negative")
        clauses: list[str] = []
        params: list[Any] = []
        if problem_type is not None:
            clauses.append("problem_type = ?")
            params.append(problem_type)
        if solver_name is not None:
            clauses.append("solver_name = ?")
            params.append(solver_name)
        if backend_name is not None:
            clauses.append("backend_name = ?")
            params.append(backend_name)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if problem_id is not None:
            clauses.append("problem_id = ?")
            params.append(problem_id)
        if run_ids is not None:
            if not run_ids:
                return [], 0
            placeholders = ", ".join("?" for _ in run_ids)
            clauses.append(f"run_id IN ({placeholders})")
            params.extend(sorted(run_ids))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connection() as connection:
            total = int(
                connection.execute(f"SELECT COUNT(*) FROM runs{where}", params).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT run_id, benchmark_id, created_at, problem_id, problem_type,
                       solver_name, status, objective, feasible, wall_time_seconds,
                       backend_type, backend_name, seed
                FROM runs{where}
                ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows], total

    def problem_run_count(self, run_ids: list[str] | tuple[str, ...]) -> dict[str, int]:
        """Count runs per problem_id for a set of run IDs (e.g. campaign members)."""
        if not run_ids:
            return {}
        placeholders = ", ".join("?" for _ in run_ids)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT problem_id, COUNT(*) AS n FROM runs "
                f"WHERE run_id IN ({placeholders}) GROUP BY problem_id",
                tuple(run_ids),
            ).fetchall()
        return {row["problem_id"]: int(row["n"]) for row in rows}

    def iter_problem_summaries(self) -> list[dict[str, Any]]:
        """List all problems stored with runs, with size metadata extracted."""
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT p.problem_id, p.problem_type, p.definition_json, p.created_at,
                       COUNT(r.run_id) AS run_count
                FROM problems p LEFT JOIN runs r ON r.problem_id = p.problem_id
                GROUP BY p.problem_id
                ORDER BY p.created_at DESC
                """
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            definition = json.loads(row["definition_json"])
            summary: dict[str, Any] = {
                "problem_id": row["problem_id"],
                "problem_type": row["problem_type"],
                "family": definition.get("family", row["problem_type"]),
                "sense": definition.get("sense"),
                "created_at": row["created_at"],
                "run_count": int(row["run_count"]),
                "size": _problem_size_hint(row["problem_type"], definition),
            }
            results.append(summary)
        return results

    def iter_problem_run_summaries(self, problem_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT run_id, solver_name, status, objective, feasible,
                       wall_time_seconds, backend_name, created_at
                FROM runs WHERE problem_id = ? ORDER BY created_at DESC
                """,
                (problem_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_problem_definition(self, problem_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT definition_json FROM problems WHERE problem_id = ?", (problem_id,)
            ).fetchone()
        if row is None:
            raise ValidationError(f"Problem not found: {problem_id}")
        return json.loads(row["definition_json"])

    def exact_objective(self, problem_id: str) -> float | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT MAX(objective) AS objective FROM runs
                WHERE problem_id = ? AND solver_name = 'exact'
                  AND status = 'success' AND feasible = 1
                """,
                (problem_id,),
            ).fetchone()
        return None if row is None else row["objective"]

    def count(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
