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

## v0.6 — analysis, reporting, and scaling

- richer benchmark comparison JSON with additive v1 schema fields;
- reproducible report generation and optional visualization helpers;
- scaling summaries, problem-size sensitivity, and resource-use exports;
- classical baseline refinements only where they add clear scientific value.

## v0.7 and later — heterogeneous execution, physical QPU exploration, and adapters

- explicitly authorized physical QPU execution;
- heterogeneous resources, optional remote workers, HPC/Slurm exploration,
  optional server/API mode, and optional web UI.

Possible external applications include cybersecurity, AI-agent scheduling,
logistics, graph optimization, scientific computing, and materials research.
They should use adapters rather than define VariaQ core.

## Recommended next milestone: 0.6

The architecture introduced in 0.5 naturally points to v0.6:

1. Build reproducible reports and optional visualizations on top of the
   normalized result model.
2. Add richer benchmark comparison fields and export helpers without breaking
   schema version 1.
3. Evaluate small classical-baseline refinements only where they add clear
   scientific value.

This keeps the next cycle focused on analysis and reporting rather than
introducing unrelated large features.
