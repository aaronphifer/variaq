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

## v0.4 — generalized problem families and adapters

- refine interfaces from concrete use;
- add independently verifiable reference problems;
- document domain adapters.

## v0.5 — analysis and reporting

- scaling summaries, export, reproducible reports, and optional visualization.

## v0.6 and later — heterogeneous execution, physical QPU exploration, and adapters

- explicitly authorized physical QPU execution;
- heterogeneous resources, optional remote workers, HPC/Slurm exploration,
  optional server/API mode, and optional web UI.

Possible external applications include cybersecurity, AI-agent scheduling,
logistics, graph optimization, scientific computing, and materials research.
They should use adapters rather than define VariaQ core.
