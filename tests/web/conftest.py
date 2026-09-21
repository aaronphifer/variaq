"""Shared fixtures for web tests: a synthetic DB and a TestClient."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from variaq.services import VariaQService
from variaq.web.app import create_app

pytestmark = pytest.mark.usefixtures("_web_deps")


@pytest.fixture(name="_web_deps")
def web_deps_guard():
    pytest.importorskip("fastapi")
    pytest.importorskip("uvicorn")
    pytest.importorskip("jinja2")
    return True


def _write_maxcut_problem(path: Path, problem_id: str, nodes: int, seed: int) -> None:
    edges = [[i, (i + 1) % nodes] for i in range(nodes)]
    doc = {
        "problem_id": problem_id,
        "problem_type": "maxcut",
        "family": "maxcut",
        "schema_version": 1,
        "sense": "maximize",
        "node_count": nodes,
        "edges": edges,
        "generation": {"seed": seed, "edge_probability": 0.4},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _make_service(base: Path) -> VariaQService:
    problems_dir = base / "problems"
    reports_dir = base / "reports"
    problems_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    return VariaQService(
        db_path=base / "variaq.sqlite3", problems_dir=problems_dir, reports_dir=reports_dir
    )


@pytest.fixture
def web_env(tmp_path):
    """A service + client over a synthetic SQLite DB with seeded runs."""
    from variaq.models import ExperimentRun, SolverConfig, utc_now
    from variaq.problems.maxcut import MaxCutProblem
    from variaq.solvers.base import get_solver

    service = _make_service(tmp_path)

    problem = MaxCutProblem.generate(6, 0.5, 11)
    for solver_name in ("exact", "heuristic"):
        solver = get_solver(solver_name)
        result = solver.solve(problem, SolverConfig(seed=3))
        service.store.save(
            ExperimentRun(
                run_id=f"run-test-{solver_name}",
                benchmark_id=None,
                created_at=utc_now(),
                problem=problem.to_dict(),
                solver_config=SolverConfig(seed=3),
                result=result,
                environment={"packages": {"variaq": "0.7.0"}},
            )
        )
    client = TestClient(create_app(service))
    return {
        "service": service,
        "client": client,
        "db": service.db_path,
        "problems_dir": service.problems_dir,
        "reports_dir": service.reports_dir,
        "problem": problem,
    }


@pytest.fixture
def empty_web_env(tmp_path):
    base = tmp_path / "empty"
    service = _make_service(base)
    return {"service": service, "client": TestClient(create_app(service))}
