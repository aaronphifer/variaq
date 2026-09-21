"""Contract tests: scientific label separation, provenance, objective sense."""

from __future__ import annotations

import json
import time
from pathlib import Path

STATIC = Path(__file__).parent.parent.parent / "src" / "variaq" / "web" / "static"
TEMPLATES = Path(__file__).parent.parent.parent / "src" / "variaq" / "web" / "templates"


def test_js_distinguishes_objective_expectation_bqm_energy():
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert '["Objective (decoded solution)"' in app_js
    assert "Expectation (optimized candidate)" in app_js
    assert "BQM energy, best decoded sample (lowered)" in app_js
    # No display path presents expectation as the objective.
    assert '["Objective"' not in app_js.replace('["Objective (decoded solution)"', "")


def test_js_distinguishes_feasible_and_infeasible_samples():
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "Feasible samples" in app_js
    assert "Infeasible samples" in app_js


def test_secondary_bundle_and_charts_have_bounded_browser_layout():
    """Guard the real-browser failures found during 0.7 release hardening."""
    app2_js = (STATIC / "app2.js").read_text(encoding="utf-8")
    campaign_template = (TEMPLATES / "campaign_detail.html").read_text(encoding="utf-8")
    css = (STATIC / "app.css").read_text(encoding="utf-8")

    # app.js and app2.js are classic scripts. app2 must have a private lexical
    # scope so destructured helper names do not redeclare app.js globals.
    assert app2_js.index("(function () {") < app2_js.index("const { apiGet")
    assert app2_js.rstrip().endswith("})();")

    # Chart.js with maintainAspectRatio=false needs a fixed-height parent;
    # otherwise responsive grid sizing can create a runaway resize loop.
    assert campaign_template.count('class="chart-canvas"') == 4
    assert ".chart-canvas { position: relative; height: 220px; }" in css


def test_run_detail_surfaces_bounded_escaped_run_messages():
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "(r.warnings || []).slice(0, 10)" in app_js
    assert "(r.errors || []).slice(0, 10)" in app_js
    assert "warnings.map(w => `<li>${esc(w)}</li>`" in app_js
    assert "errors.map(error => `<li>${esc(error)}</li>`" in app_js


def test_js_renders_known_links_without_trusting_api_text():
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    app2_js = (STATIC / "app2.js").read_text(encoding="utf-8")
    assert "function html(value)" in app_js
    assert 'Object.hasOwn(v, "variaqSafeHtml")' in app_js
    assert '["Problem", html(' in app_js
    assert '? html(`<a href="/campaigns/' in app2_js


def test_js_displays_unknown_boolean_as_empty_value():
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'if (v === null || v === undefined) return "—"' in app_js
    assert "boolText(Boolean(r.feasible))" not in app_js


def test_problem_listing_exposes_sense(web_env):
    row = web_env["client"].get("/api/v1/problems").json()["problems"][0]
    assert row["sense"] == "maximize"


def _wait(client, task_id):
    current: dict | None = None
    for _ in range(240):
        current = client.get(f"/api/v1/campaigns/tasks/{task_id}").json()["task"]
        if current is not None and current["status"] == "completed":
            return current
        time.sleep(0.05)
    raise AssertionError("campaign task did not complete")


def test_campaign_analysis_exposes_source_run_count(web_env):
    client = web_env["client"]
    client.post(
        "/api/v1/campaigns/run",
        json={
            "definition": {
                "name": "prov",
                "family": "maxcut",
                "problem_sizes": [4],
                "problem_seeds": [1],
                "solvers": ["exact"],
                "repeats": 1,
                "generator_parameters": {"edge_probability": 0.5},
            }
        },
    )
    task = client.get("/api/v1/campaigns/tasks/current").json()["task"]
    current = _wait(client, task["task_id"])
    campaign_id = current["campaign_id"]
    analysis = client.post(f"/api/v1/analysis/campaigns/{campaign_id}", json={}).json()
    assert len(analysis["source_run_ids"]) == 1

    created = client.post(
        f"/api/v1/reports/campaigns/{campaign_id}", json={"formats": ["json"]}
    ).json()
    report = client.get(f"/api/v1/reports/{created['report_id']}").json()
    assert report["report"]["source_run_ids"] == analysis["source_run_ids"]


def test_run_detail_preserves_rerun_lineage(web_env):
    service = web_env["service"]
    from variaq.models import utc_now

    original = service.store.get("run-test-exact")
    rerun = type(original)(
        run_id="run-test-rerun",
        benchmark_id=None,
        created_at=utc_now(),
        problem=original.problem,
        solver_config=original.solver_config,
        result=original.result,
        environment=original.environment,
        rerun_of="run-test-exact",
    )
    service.store.save(rerun)
    data = web_env["client"].get("/api/v1/runs/run-test-rerun").json()
    assert data["rerun_of"] == "run-test-exact"


def test_empty_states_render(web_env, empty_web_env):
    page = empty_web_env["client"].get("/")
    assert "empty-hint" in page.text or "No experiments" in page.text
    reports_page = empty_web_env["client"].get("/reports")
    assert reports_page.status_code == 200


def test_run_json_has_no_python_repr_leak(web_env):
    raw = web_env["client"].get("/api/v1/runs/run-test-exact").text
    parsed = json.loads(raw)  # strict parse, no repr formatting
    assert parsed["result"]["solver_name"] == "exact"


def test_run_membership_link(web_env):
    """Runs recorded by a campaign know their campaign."""
    client = web_env["client"]
    client.post(
        "/api/v1/campaigns/run",
        json={
            "definition": {
                "name": "membership",
                "family": "maxcut",
                "problem_sizes": [4],
                "problem_seeds": [1],
                "solvers": ["exact"],
                "repeats": 1,
                "generator_parameters": {"edge_probability": 0.5},
            }
        },
    )
    task = client.get("/api/v1/campaigns/tasks/current").json()["task"]
    current = _wait(client, task["task_id"])
    run_id = current["result"]["run_ids"][0]
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert any(c["campaign_id"] == current["campaign_id"] for c in detail["campaigns"])
