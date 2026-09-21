"""Security regression tests for the local web API and server configuration."""

from __future__ import annotations

import json

import pytest


def test_default_bind_is_loopback():
    from variaq.web.config import DEFAULT_HOST, WebConfig

    assert DEFAULT_HOST == "127.0.0.1"
    config = WebConfig()
    assert config.host == "127.0.0.1"
    assert config.bind_is_loopback is True
    assert config.remote_bind_warning() is None


def test_remote_bind_warning():
    from variaq.web.config import WebConfig

    config = WebConfig(host="0.0.0.0")
    warning = config.remote_bind_warning()
    assert warning is not None
    assert "WARNING" in warning
    assert "internet" in warning.lower()


def test_report_file_traversal_blocked(web_env):
    client = web_env["client"]
    # Plant a report plus a sibling file that shares the report-id prefix.
    reports_dir = web_env["reports_dir"]
    (reports_dir / "out").mkdir(parents=True)
    (reports_dir / "out" / "report-abc.json").write_text(
        json.dumps({"report_id": "report-abc", "source_run_ids": [], "analysis": {}}),
        encoding="utf-8",
    )
    (reports_dir / "out" / "secret.txt").write_text("TOP SECRET", encoding="utf-8")

    for bad in (
        "../secret.txt",
        "..%2Fsecret.txt",
        "..\\secret.txt",
        "%2E%2E/secret.txt",
        "secret.txt",
        "report-abc/../secret.txt",
    ):
        response = client.get(f"/api/v1/reports/report-abc/files/{bad}")
        assert response.status_code in (400, 403, 404), (bad, response.status_code)
        if response.status_code == 200:
            raise AssertionError(f"traversal succeeded for {bad!r}")
    ok = client.get("/api/v1/reports/report-abc/files/report-abc.json")
    assert ok.status_code == 200
    # Other files in the directory that are not named as report artifacts are refused.
    nope = client.get("/api/v1/reports/report-abc/files/secret.txt")
    assert nope.status_code in (400, 403, 404)
    # A matching prefix is insufficient: only filenames emitted by VariaQ's
    # report exporters are downloadable.
    (reports_dir / "out" / "report-abc.private").write_text("secret", encoding="utf-8")
    prefixed = client.get("/api/v1/reports/report-abc/files/report-abc.private")
    assert prefixed.status_code == 403


def test_report_symlinks_outside_root_are_rejected(web_env):
    client = web_env["client"]
    reports_dir = web_env["reports_dir"]
    outside = reports_dir.parent / "outside"
    outside.mkdir()

    outside_report = outside / "report-outside.json"
    outside_report.write_text(
        json.dumps({"report_id": "report-outside", "source_run_ids": [], "analysis": {}}),
        encoding="utf-8",
    )
    try:
        (reports_dir / "report-outside.json").symlink_to(outside_report)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable on this platform: {exc}")

    listing = client.get("/api/v1/reports").json()
    assert all(item["report_id"] != "report-outside" for item in listing["reports"])
    assert client.get("/api/v1/reports/report-outside").status_code == 404

    valid_id = "report-inside"
    (reports_dir / f"{valid_id}.json").write_text(
        json.dumps({"report_id": valid_id, "source_run_ids": [], "analysis": {}}),
        encoding="utf-8",
    )
    outside_markdown = outside / f"{valid_id}.md"
    outside_markdown.write_text("outside root", encoding="utf-8")
    (reports_dir / f"{valid_id}.md").symlink_to(outside_markdown)
    response = client.get(f"/api/v1/reports/{valid_id}/files/{valid_id}.md")
    assert response.status_code == 403


def test_report_absolute_path_injection_blocked(web_env):
    client = web_env["client"]
    report_id = "report-abs"
    (web_env["reports_dir"] / f"{report_id}.json").write_text(
        json.dumps({"report_id": report_id, "source_run_ids": []}), encoding="utf-8"
    )
    response = client.get(f"/api/v1/reports/{report_id}/files//etc/passwd")
    assert response.status_code in (400, 403, 404)
    response2 = client.get(f"/api/v1/reports/{report_id}/files/C:%5CWindows%5Cwin.ini")
    assert response2.status_code in (400, 403, 404)


def test_unknown_report_id(web_env):
    response = web_env["client"].get("/api/v1/reports/report-missing/files/anything.json")
    assert response.status_code == 404


def test_malformed_ids(web_env):
    assert web_env["client"].get("/api/v1/runs/run-!@#$%").status_code == 404
    response = web_env["client"].get("/api/v1/problems/%2E%2E")
    assert response.status_code in (400, 404, 422)


def test_invalid_json_body(web_env):
    response = web_env["client"].post(
        "/api/v1/campaigns/plan",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code in (400, 422)
    body = response.json()
    # No traceback leaks to the client.
    assert "Traceback" not in json.dumps(body)


def test_schema_validation_errors_are_clean(web_env):
    response = web_env["client"].post("/api/v1/campaigns/plan", json={"definition": {"name": 42}})
    assert response.status_code == 422
    body = json.dumps(response.json())
    assert "Traceback" not in body


def test_no_shell_or_sql_or_env_endpoints(web_env):
    client = web_env["client"]
    for path in (
        "/api/v1/shell",
        "/api/v1/exec",
        "/api/v1/sql",
        "/api/v1/query",
        "/api/v1/env",
        "/api/v1/files",
        "/api/v1/fs",
    ):
        assert client.get(path).status_code == 404, path


def test_capabilities_do_not_leak_environment(web_env):
    data = web_env["client"].get("/api/v1/capabilities").json()
    text = json.dumps(data)
    assert "HOME" not in text or "HOME" == "home"  # no env map dump
    assert "/home/" not in text.replace("problem_families", "")
    assert "SECRET" not in text and "PASSWORD" not in text


def test_capability_probing_does_not_mutate_storage(web_env):
    """Reading capabilities/overview must not create problems or runs.

    Regression guard: a UI status read is pure. The capability probe executes a
    tiny solver in-process; it must never persist to ExperimentStore.
    """
    client = web_env["client"]
    before_problems = client.get("/api/v1/problems").json()["total"]
    before_runs = client.get("/api/v1/runs").json()["total"]
    # Exercise every read path that internally gathers capabilities.
    client.get("/api/v1/capabilities")
    client.get("/api/v1/overview")
    client.post(
        "/api/v1/campaigns/plan",
        json={
            "definition": {
                "name": "probe",
                "family": "maxcut",
                "problem_sizes": [4],
                "problem_seeds": [1],
                "solvers": ["exact"],
                "repeats": 1,
            }
        },
    )
    after_problems = client.get("/api/v1/problems").json()["total"]
    after_runs = client.get("/api/v1/runs").json()["total"]
    assert after_problems == before_problems
    assert after_runs == before_runs


def test_no_docs_or_debug_attack_surface(web_env):
    client = web_env["client"]
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_web_command_message_without_extra(monkeypatch, capsys):
    """`variaq web` without the web extra prints an actionable hint, not a traceback."""
    import sys
    from importlib import import_module

    import variaq.web as web_pkg

    cli = import_module("variaq.cli")

    monkeypatch.setattr(web_pkg, "web_dependencies_available", lambda: False)
    monkeypatch.setitem(sys.modules, "variaq.web", web_pkg)
    code = cli.main(["web"])
    assert code == 2
    captured = capsys.readouterr()
    assert "pip install 'variaq[web]'" in captured.err
    assert "Traceback" not in captured.err


def test_web_command_uses_configured_report_root(monkeypatch, tmp_path):
    """The CLI must pass the dataset's explicit report root to the web service."""
    from importlib import import_module

    import variaq.web as web_pkg
    from variaq.web import server

    cli = import_module("variaq.cli")
    captured = {}
    reports_dir = tmp_path / "dataset-reports"

    monkeypatch.setattr(web_pkg, "web_dependencies_available", lambda: True)

    def fake_serve(config):
        captured["config"] = config
        return 0

    monkeypatch.setattr(server, "serve", fake_serve)
    code = cli.main(
        [
            "--db",
            str(tmp_path / "dataset.sqlite3"),
            "--problems-dir",
            str(tmp_path / "problems"),
            "web",
            "--reports-dir",
            str(reports_dir),
        ]
    )

    assert code == 0
    assert captured["config"].reports_dir == reports_dir
