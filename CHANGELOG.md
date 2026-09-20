# Changelog

VariaQ follows semantic versioning while pre-1.0. Release dates will be added
when a public release is created.

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
