# Web UI architecture decision (VariaQ 0.7.0)

## Chosen architecture

**FastAPI (backend) + Jinja2 server-rendered templates + vanilla JavaScript + Chart.js (vendored).**

- One ASGI app (`variaq.web.app`) serves both the versioned JSON API (`/api/v1/`)
  and HTML pages.
- HTML pages are server-rendered Jinja2 templates; lightweight vanilla JS fetches
  structured JSON from the same origin for dynamic tables, charts, and forms.
- Chart.js is vendored as a single static file. No Node.js, bundler, or frontend
  build step exists at runtime or for contributors.
- The web layer talks to a shared application/service module
  (`variaq.services`) which wraps the existing VariaQ subsystems. The browser
  never touches SQLite directly and never computes scientific metrics.

## Why

| Requirement | How this stack meets it |
|---|---|
| Python backend integrates naturally with VariaQ | FastAPI is pure Python; services import VariaQ modules directly. |
| Optional dependency from base VariaQ | `[web]` extra only: fastapi, uvicorn, jinja2, python-multipart. Base install unchanged. |
| Minimal toolchain complexity | No Node/npm/Vite. Templates + static files shipped in the wheel. |
| Responsive research dashboard | Server-rendered HTML + CSS grid/flex; JS only for charts and async updates. |
| Charts/tables manageable | Chart.js consumes structured `AnalysisResult` JSON; tables render from bounded list endpoints. |
| Testable | FastAPI's `TestClient` (httpx) exercises API and HTML without a browser. |
| Maintainable by outside contributors | Plain Python + HTML/CSS/JS; no transpilation or framework lock-in beyond FastAPI/Jinja. |
| Local-first, safe defaults | FastAPI/uvicorn bind to 127.0.0.1 by default; warning on non-loopback. |

## Alternatives considered

**B. FastAPI + React/Vite.** Rejected for 0.7.0: introduces Node.js as a build
prerequisite, a compiled-frontend packaging problem, TypeScript codegen pressure,
and a large amount of tooling for an interface whose interactivity needs
(tables, forms, a handful of charts) are modest. The milestone explicitly
prefers avoiding a large frontend build system unless it materially improves
the product; it does not here. The API boundary being established means a
compiled SPA can be added later without changing the backend.

**C. NiceGUI / Reflex / Panel / Streamlit.** Rejected: these couple UI widgets to
Python objects, which invites business logic into the presentation layer and
makes the clean API boundary (needed for future integrations) harder to keep
honest. Streamlit in particular is multi-document-unfriendly and has weak
control over information density and navigation structure.

**D. HTMX-heavy partial-page swaps.** Considered as a variant of the chosen
stack. A small amount of fetch-based JS was judged simpler than introducing an
HTMX dependency for the handful of dynamic regions; charts need real JS anyway.

## Packaging implications

- `templates/` and `static/` live inside `src/variaq/web/` and are included in
  the wheel via hatchling package data. Running the UI requires only
  `pip install 'variaq[web]'`.
- No `node_modules`, source maps, or dev-server files are shipped.
- Base install (no `[web]`) remains dependency-free of FastAPI/uvicorn/Jinja2;
  `variaq web` prints an actionable install hint rather than a traceback.

## Development workflow

    pip install -e ".[web,dev]"
    variaq web               # serves http://127.0.0.1:8701
    pytest tests/web         # API + template tests, no browser needed

## Future extension path

- The `/api/v1/` contract is the stable boundary: a React/Vite SPA, a TUI, or
  third-party integrations can consume it without touching server code.
- Campaign task tracking is intentionally in-process and single-flight; a richer
  progress model can be added behind the same `/api/v1/campaigns/tasks/`
  endpoints without breaking the UI.
