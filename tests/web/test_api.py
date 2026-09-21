"""Read-only API tests: capabilities, problems, runs, campaigns, analysis, reports."""

from __future__ import annotations


def test_capabilities(web_env):
    data = web_env["client"].get("/api/v1/capabilities").json()
    assert data["variaq"]["version"]
    assert data["physical_qpu"]["supported"] is False
    solver_names = [s["name"] for s in data["solvers"]]
    assert "exact" in solver_names and "heuristic" in solver_names
    # Solver matrices are dynamic from VariaQ, not hardcoded in the frontend.
    exact = next(s for s in data["solvers"] if s["name"] == "exact")
    assert "maxcut" in exact["supported_families"]


def test_overview_counts_and_recents(web_env):
    data = web_env["client"].get("/api/v1/overview").json()
    assert data["counts"]["runs"] == 2
    assert data["counts"]["problems"] == 1
    assert data["counts"]["campaigns"] == 0
    assert len(data["recent_runs"]) == 2


def test_empty_dashboard_overview(empty_web_env):
    data = empty_web_env["client"].get("/api/v1/overview").json()
    assert data["counts"] == {"problems": 0, "runs": 0, "campaigns": 0, "reports": 0}
    assert data["recent_runs"] == []
    page = empty_web_env["client"].get("/")
    assert page.status_code == 200


def test_problem_list_and_detail(web_env):
    problem_id = web_env["problem"].problem_id
    listing = web_env["client"].get("/api/v1/problems").json()
    assert listing["total"] == 1
    row = listing["problems"][0]
    assert row["problem_id"] == problem_id
    assert row["sense"] == "maximize"
    assert row["size"]["nodes"] == 6

    detail = web_env["client"].get(f"/api/v1/problems/{problem_id}").json()
    assert detail["family"] == "maxcut"
    assert detail["exact_objective"] is not None
    assert detail["runs"]["total"] == 2


def test_problem_filters(web_env):
    ok = web_env["client"].get("/api/v1/problems?family=maxcut").json()
    assert ok["total"] == 1
    miss = web_env["client"].get("/api/v1/problems?family=assignment").json()
    assert miss["total"] == 0
    search = web_env["client"].get("/api/v1/problems?search=nope").json()
    assert search["total"] == 0


def test_runs_list_filters_and_pagination(web_env):
    data = web_env["client"].get("/api/v1/runs").json()
    assert data["total"] == 2

    exact_only = web_env["client"].get("/api/v1/runs?solver=exact").json()
    assert exact_only["total"] == 1
    assert exact_only["runs"][0]["solver_name"] == "exact"

    page = web_env["client"].get("/api/v1/runs?limit=1&offset=1").json()
    assert page["total"] == 2
    assert len(page["runs"]) == 1

    bad_status = web_env["client"].get("/api/v1/runs?status=bogus")
    assert bad_status.status_code == 400


def test_run_detail_scientific_fields(web_env):
    data = web_env["client"].get("/api/v1/runs/run-test-exact").json()
    result = data["result"]
    # Objective is stored distinctly from quantum expectation/energy metadata.
    assert result["objective"] is not None
    assert "optimized_expected_objective" not in result  # not conflated at top level
    assert data["campaigns"] == []
    assert data["rerun_of"] is None


def test_missing_resources_are_404(web_env):
    assert web_env["client"].get("/api/v1/runs/run-nope").status_code == 404
    assert web_env["client"].get("/api/v1/problems/nope").status_code == 404
    assert web_env["client"].get("/api/v1/campaigns/campaign-nope").status_code == 404
    assert web_env["client"].get("/api/v1/reports/report-nope").status_code == 404


def test_run_and_campaign_limit_bounds(web_env):
    assert web_env["client"].get("/api/v1/runs?limit=0").status_code == 400
    assert web_env["client"].get("/api/v1/runs?limit=1001").status_code == 400
    assert web_env["client"].get("/api/v1/runs?offset=-1").status_code == 400
    assert web_env["client"].get("/api/v1/campaigns?limit=5001").status_code == 400


def test_html_pages_render(web_env):
    for page in (
        "/",
        "/problems",
        "/runs",
        "/campaigns",
        "/campaigns/new",
        "/reports",
        "/capabilities",
    ):
        response = web_env["client"].get(page)
        assert response.status_code == 200, page
        assert "<html" in response.text
