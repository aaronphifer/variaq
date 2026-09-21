"""Uvicorn entrypoint glue for ``variaq web``."""

from __future__ import annotations

from variaq.services import VariaQService
from variaq.web.app import create_app
from variaq.web.config import WebConfig


def build_app(config: WebConfig):
    service = VariaQService(
        db_path=config.db_path,
        problems_dir=config.problems_dir,
        reports_dir=config.reports_dir,
    )
    return create_app(service)


def serve(config: WebConfig) -> int:
    warning = config.remote_bind_warning()
    if warning:
        print(f"\n{warning}\n")
    app = build_app(config)
    import uvicorn

    print(f"VariaQ web UI: http://{config.host}:{config.port}  (database: {config.db_path.name})")
    uvicorn.run(app, host=config.host, port=config.port, log_level="warning")
    return 0
