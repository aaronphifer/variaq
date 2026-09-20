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

## v0.5 — generic binary quadratic / QAOA and reporting

- extend matched QAOA execution across eligible families using the lowered binary
  quadratic representation;
- stronger classical baselines;
- scaling summaries, export, reproducible reports, and optional visualization.

## v0.6 and later — heterogeneous execution, physical QPU exploration, and adapters

- explicitly authorized physical QPU execution;
- heterogeneous resources, optional remote workers, HPC/Slurm exploration,
  optional server/API mode, and optional web UI.

Possible external applications include cybersecurity, AI-agent scheduling,
logistics, graph optimization, scientific computing, and materials research.
They should use adapters rather than define VariaQ core.

## Recommended next milestone: 0.5

The architecture introduced in 0.4 naturally points to v0.5:

1. Implement generic QAOA over the backend-neutral binary quadratic model for
   families where the lowered representation is verified.
2. Add stronger classical baselines (e.g. simulated annealing reference, local
   search with swap moves).
3. Build reproducible reports and optional visualizations on top of the
   normalized result model.

This keeps 0.5 focused on extending the 0.4 foundation rather than introducing
unrelated large features.
