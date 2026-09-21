"""VariaQ local web UI: FastAPI application factory.

Local-first, research-tool interface over :class:`VariaQService`. The browser
never queries SQLite and never computes scientific results; everything below
returns VariaQ's own serialized domain objects.

Security model: loopback-only by default (see ``variaq.web.server``), no shell,
no raw SQL, no arbitrary file reads. Report downloads are restricted to files
registered to a known report artifact inside the configured reports root.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError as PydanticValidationError

from variaq.errors import SolverLimitError, ValidationError, VariaQError
from variaq.services import VariaQService
from variaq.web.schemas import (
    AnalysisRequest,
    CampaignPlanRequest,
    CampaignRunRequest,
    ReportRequest,
)
from variaq.web.tasks import CampaignTaskManager

log = logging.getLogger("variaq.web")

PACKAGE_DIR = Path(__file__).parent
TEMPLATE_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

API_PREFIX = "/api/v1"


def create_app(
    service: VariaQService,
    *,
    task_manager: CampaignTaskManager | None = None,
) -> FastAPI:
    app = FastAPI(
        title="VariaQ",
        version="1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.service = service
    tasks = task_manager or CampaignTaskManager()
    app.state.tasks = tasks

    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    app.state.templates = templates
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # -- error mapping ---------------------------------------------------------

    @app.exception_handler(ValidationError)
    async def variaq_validation_error(_request: Request, exc: ValidationError) -> JSONResponse:
        message = str(exc)
        status = 400
        if message.startswith(
            (
                "Run not found",
                "Problem not found",
                "Campaign not found",
                "Report not found",
                "Report file not found",
                "No saved problem file",
            )
        ):
            status = 404
        elif message.startswith(("Campaign requests", "Requested file")):
            status = 403 if message.startswith("Requested file") else 400
        return JSONResponse(
            status_code=status,
            content={"error": {"type": "ValidationError", "message": message}},
        )

    @app.exception_handler(SolverLimitError)
    async def solver_limit_error(_request: Request, exc: SolverLimitError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "SolverLimitError", "message": str(exc)}},
        )

    @app.exception_handler(PydanticValidationError)
    async def schema_error(_request: Request, exc: PydanticValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "SchemaError",
                    "message": "Request body failed validation",
                    "details": exc.errors(include_url=False),
                }
            },
        )

    @app.exception_handler(VariaQError)
    async def variaq_error(_request: Request, exc: VariaQError) -> JSONResponse:
        log.exception("VariaQ error handling %s", _request.url.path)
        return JSONResponse(
            status_code=400,
            content={"error": {"type": type(exc).__name__, "message": str(exc)}},
        )

    @app.exception_handler(Exception)
    async def unhandled_error(_request: Request, exc: Exception) -> JSONResponse:
        # Internal details are logged locally, never echoed to the client.
        log.exception("Unhandled error handling %s", _request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": {"type": "InternalError", "message": "Internal server error"}},
        )

    def svc() -> VariaQService:
        return app.state.service

    # -- API: capabilities / overview -------------------------------------------

    @app.get(f"{API_PREFIX}/capabilities")
    def api_capabilities() -> dict[str, Any]:
        return svc().capabilities()

    @app.get(f"{API_PREFIX}/overview")
    def api_overview() -> dict[str, Any]:
        return svc().overview()

    @app.get(f"{API_PREFIX}/health")
    def api_health() -> dict[str, str]:
        return {"status": "ok"}

    # -- API: problems -------------------------------------------------------------

    @app.get(f"{API_PREFIX}/problems")
    def api_problems(
        family: str | None = None,
        search: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        return svc().list_problems(family=family, search=search, limit=limit, offset=offset)

    @app.get(f"{API_PREFIX}/problems/{{problem_id}}")
    def api_problem(problem_id: str) -> dict[str, Any]:
        return svc().get_problem(problem_id)

    @app.get(f"{API_PREFIX}/problems/{{problem_id}}/file")
    def api_problem_file(problem_id: str) -> dict[str, Any]:
        return svc().get_problem_file(problem_id)

    # -- API: runs -----------------------------------------------------------------

    @app.get(f"{API_PREFIX}/runs")
    def api_runs(
        family: str | None = None,
        solver: str | None = None,
        backend: str | None = None,
        status: str | None = None,
        campaign_id: str | None = None,
        problem_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        return svc().list_runs(
            family=family,
            solver=solver,
            backend=backend,
            status=status,
            campaign_id=campaign_id,
            problem_id=problem_id,
            limit=limit,
            offset=offset,
        )

    @app.get(f"{API_PREFIX}/runs/{{run_id}}")
    def api_run(run_id: str) -> dict[str, Any]:
        return svc().get_run(run_id)

    # -- API: campaigns ------------------------------------------------------------

    @app.get(f"{API_PREFIX}/campaigns")
    def api_campaigns(limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return svc().list_campaigns(limit=limit, offset=offset)

    @app.get(f"{API_PREFIX}/campaigns/tasks/current")
    def api_campaign_task_current(request: Request) -> dict[str, Any]:
        task = request.app.state.tasks.current()
        return {"task": task.to_dict() if task else None}

    @app.get(f"{API_PREFIX}/campaigns/tasks/{{task_id}}")
    def api_campaign_task(task_id: str, request: Request) -> dict[str, Any]:
        task = request.app.state.tasks.get(task_id)
        if task is None:
            raise HTTPException(
                status_code=404,
                detail={"type": "TaskNotFound", "message": f"No such task: {task_id}"},
            )
        return {"task": task.to_dict()}

    @app.get(f"{API_PREFIX}/campaigns/{{campaign_id}}")
    def api_campaign(campaign_id: str) -> dict[str, Any]:
        return svc().get_campaign(campaign_id)

    @app.post(f"{API_PREFIX}/campaigns/plan")
    def api_campaign_plan(payload: CampaignPlanRequest) -> dict[str, Any]:
        return svc().plan_campaign(payload.definition.to_definition())

    @app.post(f"{API_PREFIX}/campaigns/run")
    def api_campaign_run(payload: CampaignRunRequest, request: Request) -> dict[str, Any]:
        definition = payload.definition.to_definition()
        plan = svc().plan_campaign(definition)
        task = request.app.state.tasks.start(
            svc(),
            definition,
            override_max_runs=payload.override_max_runs,
            max_runs=payload.max_runs,
            planned_runs=plan.get("requested_runs"),
        )
        if task is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "type": "CampaignInProgress",
                    "message": "A campaign is already running in this server process.",
                },
            )
        return {"task": task.to_dict(), "plan": plan}

    # -- API: analysis -------------------------------------------------------------

    @app.post(f"{API_PREFIX}/analysis/runs")
    def api_analysis_runs(payload: AnalysisRequest) -> dict[str, Any]:
        return svc().analyze(
            campaign_id=payload.campaign_id,
            run_ids=payload.run_ids,
            filters=payload.filters,
            group_by=payload.group_by,
            scaling_x=payload.scaling_x,
            include_failed=payload.include_failed,
            include_unavailable=payload.include_unavailable,
            comparisons=payload.comparisons,
        )

    @app.post(f"{API_PREFIX}/analysis/campaigns/{{campaign_id}}")
    def api_analysis_campaign(campaign_id: str, payload: AnalysisRequest) -> dict[str, Any]:
        return svc().analyze(
            campaign_id=campaign_id,
            filters=payload.filters,
            group_by=payload.group_by,
            scaling_x=payload.scaling_x,
            include_failed=payload.include_failed,
            include_unavailable=payload.include_unavailable,
            comparisons=payload.comparisons,
        )

    # -- API: reports --------------------------------------------------------------

    @app.get(f"{API_PREFIX}/reports")
    def api_reports() -> dict[str, Any]:
        return svc().list_reports()

    @app.get(f"{API_PREFIX}/reports/{{report_id}}")
    def api_report(report_id: str) -> dict[str, Any]:
        return svc().get_report(report_id)

    @app.post(f"{API_PREFIX}/reports/campaigns/{{campaign_id}}")
    def api_report_create(campaign_id: str, payload: ReportRequest) -> dict[str, Any]:
        return svc().create_report(
            campaign_id,
            formats=list(payload.formats) if payload.formats else None,
            group_by=payload.group_by,
            scaling_x=payload.scaling_x,
            comparisons=payload.comparisons,
            plots=payload.plots,
            overwrite=payload.overwrite,
        )

    @app.get(f"{API_PREFIX}/reports/{{report_id}}/files/{{filename}}")
    def api_report_file(report_id: str, filename: str) -> FileResponse:
        path = svc().get_report_file_path(report_id, filename)
        return FileResponse(path)

    # -- HTML pages ----------------------------------------------------------------

    def page(request: Request, name: str, **context: Any) -> Any:
        return templates.TemplateResponse(
            request,
            name,
            {"api_prefix": API_PREFIX, "active_page": name.split(".")[0], **context},
        )

    @app.get("/", include_in_schema=False)
    def dashboard(request: Request) -> Any:
        return page(request, "dashboard.html")

    @app.get("/problems", include_in_schema=False)
    def problems(request: Request) -> Any:
        return page(request, "problems.html")

    @app.get("/problems/{problem_id}", include_in_schema=False)
    def problem_detail(request: Request, problem_id: str) -> Any:
        return page(request, "problem_detail.html", problem_id=problem_id)

    @app.get("/runs", include_in_schema=False)
    def runs(request: Request) -> Any:
        return page(request, "runs.html")

    @app.get("/runs/{run_id}", include_in_schema=False)
    def run_detail(request: Request, run_id: str) -> Any:
        return page(request, "run_detail.html", run_id=run_id)

    @app.get("/campaigns", include_in_schema=False)
    def campaigns(request: Request) -> Any:
        return page(request, "campaigns.html")

    @app.get("/campaigns/new", include_in_schema=False)
    def campaign_new(request: Request) -> Any:
        return page(request, "campaign_new.html")

    @app.get("/campaigns/{campaign_id}", include_in_schema=False)
    def campaign_detail(request: Request, campaign_id: str) -> Any:
        return page(request, "campaign_detail.html", campaign_id=campaign_id)

    @app.get("/reports", include_in_schema=False)
    def reports(request: Request) -> Any:
        return page(request, "reports.html")

    @app.get("/reports/{report_id}", include_in_schema=False)
    def report_detail(request: Request, report_id: str) -> Any:
        return page(request, "report_detail.html", report_id=report_id)

    @app.get("/capabilities", include_in_schema=False)
    def capabilities(request: Request) -> Any:
        return page(request, "capabilities.html")

    return app
