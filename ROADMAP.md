# VariaQ roadmap

These are directions, not implemented features or delivery commitments.

## v0.1 — reproducible core

- solver-independent problem and result models;
- MaxCut, exact and seeded classical baselines;
- Qiskit local statevector QAOA;
- append-only SQLite history.

## v0.2 — matched local simulation

- shared QAOA candidate generation;
- CUDA-Q CPU/GPU adapters;
- canonical backend normalization;
- cross-framework expectation verification;
- capability-aware unavailable outcomes.

## v0.3 — versioned structured output

- machine-readable, versioned CLI output schema;
- native JSON for solve, benchmark, compare quantum, capabilities, and run
  inspection/reproduction;
- structured errors/warnings and capability reporting;
- strengthened reproduction and environment-diff contracts;
- interface hardening across Linux, Windows, and macOS.

## v0.4 — generalized problem families and domain adapters

- domain-neutral Assignment, Subset Selection, and Graph Partitioning families;
- canonical problem definitions, serialization, validation, and authoritative
  evaluation for each family;
- solver/problem-family capability matrix;
- exact reference solvers and seeded heuristics for all new families;
- objective-sense-aware metrics (maximize/minimize);
- optional backend-neutral binary quadratic lowering;
- public Domain Adapter SDK and adapter scaffolding command;
- problem import/export and deterministic reference generators;
- updated documentation and examples.

## v0.5 — generic binary quadratic / QAOA (completed scope)

- authoritative backend-neutral `BinaryQuadraticModel` with documented convention,
  validation, canonical pair ordering, and stable digests;
- generic QAOA layer (`QAOAProblem`) that consumes a BQM and is agnostic to
  problem-family semantics;
- Qiskit and CUDA-Q CPU/GPU adapters refactored to use the same BQM,
  variable ordering, parameter vectors, and Ising convention;
- MaxCut migrated to the generic BQM path while preserving established numeric
  behavior;
- Assignment, Subset Selection, and Graph Partitioning enabled on the generic
  QAOA path where the lowered representation is verified;
- explicit penalty construction and metadata for constrained families;
- decoded quantum samples evaluated by the original problem instance;
- structured feasible/infeasible sample reporting, constraint violations, and
  best-infeasible metrics;
- resource guards based on binary variable count and estimated statevector memory;
- `variaq compare quantum` generalized to any family supported by the selected
  quantum solvers;
- capability matrix derived from solver `supported_families` declarations.

## v0.6 — analysis, reporting, and scaling (completed in 0.6.0)

- domain-neutral `ExperimentCampaign` definitions with deterministic IDs;
- bounded local campaign runner with default run-count guard and failure isolation;
- campaign/run membership persistence via additive SQLite tables;
- domain-neutral analysis layer with typed grouping, quality, feasibility, timing,
  resource, repeat, and scaling summaries;
- objective-sense-aware metrics and structured feasibility analysis;
- classical-vs-quantum, Qiskit-vs-CUDA-Q, and GPU-vs-CPU comparisons;
- reproducible `ReportArtifact` model with deterministic IDs;
- JSON, CSV, and Markdown report exports;
- optional matplotlib plot generation from analysis data.

## v0.7 — local web UI (completed scope)

- optional local-first web interface over a shared application service layer;
- versioned local JSON API (`/api/v1/`) with loopback-only default binding;
- dashboard, problems, runs, campaigns, analysis, reports, and capabilities pages;
- campaign plan-before-run workflow preserving the existing max-run guard;
- in-process sequential campaign execution with status/progress (no worker queue);
- analysis-visualization charts driven by structured `AnalysisResult` data;
- safe report downloads confined to known report artifacts.

## v0.8 — reproducible scientific benchmarking (local candidate)

First development slice (implemented in this checkout, not a release):

- small opt-in MaxCut matrices over sizes, graph seeds, solver repeats, and local
  classical/Qiskit/CUDA-Q backends with existing resource guards;
- authoritative per-instance quality and exact-reference gaps, feasibility,
  conservative repeat pairing, source-run provenance, and repeat variability;
- complete-call wall time and available compute/setup/warmup layers, with explicit
  null/reason metadata for missing measurements and unverified cold starts;
- separate numerical backend agreement from speed and sampled quality;
- additive schema-v1 JSON, CSV, and Markdown reporting, documented methodology,
  and dependency-free regression coverage.

Web interface development slice (implemented in the candidate):

- cohesive dark-first responsive dashboard and navigation;
- guided experiment recipes, capability-aware solver selection, advanced QAOA
  configuration, plan invalidation, and local task recovery messaging;
- bounded comparison workspace over authoritative Python instance/repeat data,
  explicit pairing, null reasons, timing scopes, per-configuration scaling,
  and selected JSON/CSV/Markdown report exports;
- canonical run measurements, configuration/environment provenance, and local
  reproduction with saved lineage;
- keyboard-accessible scientific explanations and alternative chart data tables.

Durable SQLite task snapshots and recovery of interrupted web tasks are implemented.
Duplicate web submissions reconnect to the original task, and campaign attempts are
saved before the next solver call. CLI reruns remain explicit new executions.
See [web benchmarking workflow](docs/benchmarking-ui.md) and
[candidate hardening](docs/releases/v0.8.0-hardening.md). Hard native-call cancellation
remains deferred.

Fresh-process GPU cold-start verification, trustworthy peak memory telemetry,
confidence intervals, and interrupting hung native calls remain future design work.
See [scientific benchmark methodology](docs/scientific-benchmarks.md).

## After v0.8 — later exploration

Future candidates (none committed): richer interactive charts on the
existing API, campaign execution progress refinement, stronger classical
baselines evaluated only where they add scientific value, Graph Partition
quantum research, and optional authenticated LAN mode for trusted labs.
Physical-QPU execution, remote workers, and cloud hosting remain out of scope
pending explicit future design.

Possible external applications include cybersecurity, AI-agent scheduling,
logistics, graph optimization, scientific computing, and materials research.
They should use adapters rather than define VariaQ core.
