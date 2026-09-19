# Changelog

VariaQ follows semantic versioning while pre-1.0. Release dates will be added
when a public release is created.

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
