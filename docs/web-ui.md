# VariaQ Web UI

An optional, local-first web interface for inspecting and operating VariaQ:
capabilities, problems, runs, campaigns, analysis, and reports.

The UI sits on top of the existing VariaQ Python application layer. It never
queries SQLite directly from the browser and never recomputes scientific
results — all metrics, analyses, plans, and reports come from VariaQ itself.

## Installation

```bash
pip install -e ".[web]"
```

The base install stays usable without the web extra (exact/heuristic solvers,
CLI, storage, and analysis keep working). `variaq web` without the extra prints
an install hint.

## Starting the UI

```bash
variaq web
```

Then open <http://127.0.0.1:8701>.

| Flag | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address. Loopback-only by default. |
| `--port` | `8701` | Local port. |
| `--db` (global, before `web`) | `data/variaq.sqlite3` | Experiment database (read/write for campaigns). |
| `--problems-dir` (global, before `web`) | `data/problems` | Saved problem artifacts. |
| `--reports-dir` | `data/reports` | Report discovery and output root. |

To serve an existing dataset whose reports live elsewhere, configure all three
roots explicitly; the report path is not inferred from the database path:

```bash
variaq --db /path/to/demo.sqlite3 --problems-dir /path/to/problems \
  web --reports-dir /path/to/reports
```

Reports are written to `data/reports/` by default. Downloads remain limited to
known VariaQ artifacts beneath the configured root.

## Default bind address and security

The server binds to **127.0.0.1** by default: it is only reachable from this
machine. The 0.7 UI is local-first software with **no hardened
internet-facing authentication or authorization**.

If you deliberately bind to another address for a trusted lab LAN:

```bash
variaq web --host 0.0.0.0 --port 8701
```

VariaQ prints a prominent warning. Do not expose this UI to the public internet.
Do not treat loopback-only software as internet-ready.

## What the UI exposes

- **Dashboard** — VariaQ version, database name, problem/run/campaign/report
  counts, recent activity, solver/backend availability, physical-QPU status.
- **Campaigns** — list, detail (definition, execution summary, member runs,
  solver breakdown, analysis, reports), and a creation form with a **Plan**
  step before execution.
- **Runs** — filterable, paginated table (family, solver, backend, status,
  campaign) plus a run detail page separating objective, quantum/BQM
  diagnostics, backend metadata, and provenance.
- **Problems** — searchable list and detail pages with associated runs and
  campaigns.
- **Reports** — generated report artifacts with metadata, source-run counts,
  and safe downloads.
- **Capabilities** — the live VariaQ capability matrix.

## Campaign workflow

1. Open **Campaigns → New campaign**.
2. Fill in the family-aware form and choose **Plan campaign**.
3. Review the plan: problem instances, requested runs, per-solver breakdown,
   unavailable combinations, and warnings.
4. If the request exceeds the default maximum (500 runs), an explicit override
   checkbox appears with a plain-language warning. VariaQ's own max-run guard
   is never bypassed.
5. Choose **Run campaign**. Execution is local and sequential, owned by the
   server process; progress is visible in the UI.

## Reports

From a campaign detail page, generate JSON/CSV/Markdown (and optional matplotlib
plots). Reports preserve `source_run_ids`. Downloads are restricted to files
that belong to a known report artifact inside the reports root — the UI cannot
read arbitrary files from disk.

## Limitations (0.7.0)

- One campaign executes at a time per server process (deliberate, no worker
  queue). Task state is in-memory: if the server is stopped mid-campaign,
  already-recorded runs remain in the database, but the task progress entry is
  lost.
- No accounts, collaboration, or remote execution.
- Charts cover campaign scaling analysis only.

## Security model and non-goals

The web layer provides **no** shell execution, arbitrary Python import, raw
SQL, arbitrary filesystem browsing, credential management, or telemetry.
Write actions (campaign run, report generation) use explicit bounded schemas.

Out of scope for 0.7: physical QPU access, IBM Runtime, AWS Braket, D-Wave,
cloud accounts, internet-hosted SaaS, and any domain-specific integration.

## API

The UI is driven by the same versioned local JSON API it serves:

```
GET  /api/v1/capabilities
GET  /api/v1/overview
GET  /api/v1/problems           ?family=&search=&limit=&offset=
GET  /api/v1/problems/{id}
GET  /api/v1/runs               ?family=&solver=&backend=&status=&campaign_id=&problem_id=&limit=&offset=
GET  /api/v1/runs/{id}
GET  /api/v1/campaigns          ?limit=&offset=
GET  /api/v1/campaigns/{id}
POST /api/v1/campaigns/plan
POST /api/v1/campaigns/run
GET  /api/v1/campaigns/tasks/current
GET  /api/v1/campaigns/tasks/{task_id}
POST /api/v1/analysis/runs
POST /api/v1/analysis/campaigns/{id}
GET  /api/v1/reports
GET  /api/v1/reports/{id}
POST /api/v1/reports/campaigns/{id}
GET  /api/v1/reports/{id}/files/{filename}
GET  /api/v1/health
```

The `v1` API version is independent of the CLI's `schema_version = "1"`.
