# Changelog

VariaQ follows semantic versioning while pre-1.0. Release dates will be added
when a public release is created.

## 0.7.0 — local web UI

- Added an optional, local-first web interface (`pip install 'variaq[web]'`,
  then `variaq web`) for inspecting capabilities, problems, runs, campaigns,
  analysis, and reports. The UI is a presentation layer over VariaQ's existing
  application services; it queries no database directly from the browser and
  recomputes no scientific results.
- Added a shared application/service facade (`variaq.services`) used by the web
  server and available to future integrations, with bounded, offset-paginated,
  filterable run and problem listings.
- Added additive, read-only query methods to `ExperimentStore`
  (`query_runs`, `iter_problem_summaries`, `iter_problem_run_summaries`,
  `get_problem_definition`, `problem_run_count`) and reverse-lookup methods to
  `CampaignStore` (`campaigns_for_run`, `campaigns_for_problem`). Existing run
  records, problem artifacts, and schema version `1` are untouched.
- Added a versioned local JSON API under `/api/v1/`, independent of the CLI
  `schema_version`.
- Added `variaq web` CLI command with loopback-only default (`127.0.0.1:8701`)
  and a prominent warning when binding to a non-loopback address. The 0.7 UI is
  local-first software and makes no internet-facing security claim.
- Added `variaq.web` with a FastAPI application, Jinja2 templates, a vendored
  Chart.js for campaign-scaling charts, and no Node.js requirement at runtime.
- Campaign planning precedes execution in the UI. Campaign execution is local,
  sequential, one-at-a-time, and owned by the server process; VariaQ's
  default max-run guard (500 runs) is never bypassed and surfaces as a
  requiring-override state in the UI.
- Added run detail, problem detail, campaign detail, analysis, report, and
  capabilities pages with objective/expectation/BQM energy displayed as distinct
  labeled quantities, provenance (campaign membership, rerun lineage, source-run
  counts), and empty states for a fresh install.
- Added safe report downloads confined to files registered to a known report
  artifact inside the configured reports root; path traversal is rejected.
- Added `docs/web-ui.md` and `docs/web-ui-architecture.md`.
- Added 46 web tests (`tests/web/`) covering the API, campaign plan/run,
  analysis, report flow, scientific label contracts, loopback defaults, remote
  bind warnings, traversal, malformed input, empty states, and a regression
  guard that capability/status reads never mutate experiment storage.
- No Triagewall, Ollama Fleet, bb scheduling, physical-QPU, or cloud-provider
  code was added; `bb-plugin-variaq` is untouched.

## 0.6.0 — campaigns, analysis, and reporting

- Added domain-neutral `ExperimentCampaign` definitions with deterministic IDs,
  serializable JSON format, and family-specific generator parameters.
- Added `variaq campaign plan|run|list|show` CLI commands.
- Added bounded local campaign runner with default run-count guard and explicit
  `--override-max-runs` escape hatch.
- Added campaign/run membership persistence via additive SQLite tables; existing
  run records and schema version `1` are preserved.
- Added campaign failure isolation: one failed run does not stop the campaign.
- Added domain-neutral analysis layer (`variaq.analysis`) with typed models for
  grouping, quality, feasibility, timing, resource, repeat, and scaling summaries.
- Added objective-sense-aware quality metrics: best/worst, gap, success-at-optimum,
  and approximation ratio.
- Added structured feasibility analysis including feasible/infeasible sample
  counts and zero-feasible-run detection.
- Added timing/resource analysis with labeled scopes and null semantics for
  missing metadata.
- Added repeat statistics (mean, median, std, min, max) with single-observation handling.
- Added scaling summaries keyed to explicit x metrics.
- Added classical-vs-quantum, Qiskit-vs-CUDA-Q, and GPU-vs-CPU comparison summaries.
- Added reproducible `ReportArtifact` model with deterministic report IDs.
- Added `variaq analyze runs|campaign` and `variaq report campaign` CLI commands.
- Added JSON, CSV, and Markdown report exports with safe path handling and
  `--overwrite` guard.
- Added optional matplotlib plot generation from analysis data.
- Added `docs/campaigns.md`, `docs/analysis.md`, `docs/reporting.md`, and
  example campaigns under `examples/campaigns/`.
- Added tests for campaigns, analysis, reports, exports, provenance, objective
  sense, feasibility, scaling, and historical-record compatibility.
- Preserved `schema_version = "1"` for CLI output and existing SQLite database
  compatibility.

No physical-QPU support is added. No Triagewall, Ollama Fleet, or bb-specific
scheduling integration is added. No web UI is implemented. No commit, push, tag,
or release is performed.

## 0.5.0 — generic binary quadratic QAOA

- Introduced a backend-neutral `BinaryQuadraticModel` (`variaq.bqm`) as an
  optional solver artifact, with a documented sense-aware energy convention,
  validation, canonical pair ordering, and stable SHA-256 digests.
- Refactored the QAOA layer into a generic `QAOAProblem` built from any BQM;
  it is agnostic to domain semantics and supplies shared parameter candidates,
  variable ordering, and cost coefficients to every backend.
- Rewrote the Qiskit and CUDA-Q CPU/GPU adapters to consume the same BQM,
  fixing variable-id-to-qubit mapping and Ising-conversion so cross-framework
  expectations agree to floating-point tolerance.
- Migrated MaxCut QAOA through the generic BQM path while preserving the
  established numeric expectation and the 8-node seed-42 reference behavior.
- Enabled Assignment and Subset Selection on the generic QAOA path where the
  lowered representation is verified; exact and heuristic baselines remain
  available for all families. Graph Partition BQM lowering is implemented and
  tested but is not advertised for quantum solvers in 0.5.0.
- Centralized penalty construction in `variaq.lower` for constrained families,
  with deterministic defaults, explicit override support, and persisted penalty
  metadata in run records.
- Made decoding and feasibility explicit: every quantum sample is decoded and
  evaluated by the original problem instance; runs report feasible and infeasible
  sample counts, best feasible/infeasible energies, and constraint violations.
- Changed final sample selection to rank decoded feasible solutions by
  authoritative objective, not raw BQM energy.
- Added resource guards based on binary variable count and estimated statevector
  memory before simulator execution.
- Generalized `variaq compare quantum` to any family whose selected quantum
  solvers advertise support, preserving matched candidate vectors, ordering,
  seed, shots, decoder, and evaluator.
- Updated the capability matrix so `qaoa`, `cudaq-cpu`, and `cudaq-gpu`
  advertise `maxcut`, `assignment`, and `subset-selection` based on their actual
  `supported_families` declarations. Graph Partition remains supported only by
  classical solvers for 0.5.0.
- Preserved the machine-readable output schema version `1` and problem artifact
  format version `1`; all new JSON fields are additive.
- Preserved SQLite database compatibility for records created under VariaQ 0.1–0.4.
- Added `tests/test_bqm.py` and `tests/test_family_qaoa.py` with independent BQM
  correctness checks and family-level QAOA end-to-end tests.
- Updated `README.md`, `ROADMAP.md`, and added `docs/binary-quadratic.md` and
  `docs/quantum-optimization.md`.

No physical-QPU support is added. No Triagewall, Ollama Fleet, or bb-specific
scheduling integration is added. No commit, push, tag, or release is performed.

## 0.4.0 — generic problem families and domain adapters

- Added three domain-neutral problem families: **Assignment**, **Subset
  Selection**, and **Graph Partitioning**.
- Added canonical problem definitions, serialization, validation, deterministic
  identity, and authoritative evaluation for each new family.
- Added deterministic seeded reference-instance generators for all families via
  `variaq problem generate`.
- Added exact reference solvers and seeded multistart local-search heuristics
  for Assignment, Subset Selection, and Graph Partitioning, with explicit
  enumeration guards.
- Added solver/problem-family capability matrix; solvers declare
  `supported_families` and unsupported combinations fail with structured
  `ValidationError`.
- Generalized objective sense handling so metrics (gap, approximation ratio,
  normalized score) behave correctly for both `maximize` and `minimize`.
- Added optional backend-neutral binary quadratic lowering
  (`variaq.lower.lower_to_binary_quadratic`) with explicit penalty metadata and
  decode mapping.
- Added public Domain Adapter SDK (`variaq.adapter.DomainAdapter`,
  `AdapterResult`, `adapter_context`) for external projects.
- Added `variaq adapter init` CLI scaffolding for small external adapters.
- Added `variaq problem import` for importing machine-readable problem
  artifacts.
- Extended `variaq capabilities` and `--json` output to report supported
  families per solver and all four problem families.
- Preserved the machine-readable output schema version `1` and problem artifact
  format version `1`.
- Preserved MaxCut-only quantum solver behavior and existing SQLite database
  compatibility.
- Updated `README.md`, added `docs/problem-families.md` and
  `docs/domain-adapters.md`, and added a neutral task-assignment adapter
  example.

No physical-QPU support is added. No Triagewall, Ollama Fleet, or bb-specific
scheduling integration is added.

## 0.3.0 — versioned structured output and capabilities

- Added a versioned machine-readable CLI output schema (`schema_version = "1"`),
  independent of the VariaQ package version.
- Added `--json` structured output for `solve`, `benchmark`, `compare quantum`,
  `capabilities`, `runs show/list/reproduce`, and `problem generate/show`.
- Added the `variaq capabilities` command with human and JSON reporting of
  solver/framework availability.
- Distinguish `supported`, `installed`, and `available` for every solver and
  backend in capability output.
- Normalized errors and warnings into a stable structured envelope in JSON mode.
- Preserved meaningful exit codes (0/1/2) in JSON mode; errors are not flattened.
- Added environment-difference reporting to `runs reproduce --json`.
- Documented the reproducibility contract, including guaranteed versus
  best-effort cases.
- Hardened cross-platform JSON serialization: no NumPy scalar leakage, no
  non-finite float leakage, deterministic key ordering.
- Added tests for JSON contracts, capability semantics, failure paths, and
  stdout-only JSON output.
- Updated `README.md` and added `docs/structured-output.md`.

No physical-QPU support is added. Existing SQLite databases remain compatible.

## 0.2.0 — first public release candidate

- renamed the internal development project from Q-Lab to VariaQ before its
  first public release;
- renamed package and CLI from `qlab` to `variaq`;
- added shared matched QAOA candidates;
- added CUDA-Q CPU/GPU adapters;
- added canonical bit normalization and expectation verification;
- added capability-aware GPU behavior;
- made SQLite connection cleanup deterministic across Windows, Linux, and macOS;
- added public documentation, examples, CI, and policies.

Historical local records are not rewritten. No Q-Lab version was publicly
released.

## 0.1.0 — internal development milestone

- reproducible experiment architecture and MaxCut;
- exact, heuristic, and Qiskit local solvers;
- append-only SQLite history and reproduction lineage.
