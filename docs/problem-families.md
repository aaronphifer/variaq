# VariaQ problem families

VariaQ is a domain-neutral optimization platform. Its core understands generic
mathematical and computational concepts such as tasks, resources, candidates,
costs, capacities, budgets, graph nodes, edges, weights, partitions, objectives,
and constraints.

VariaQ core does **not** understand domain-specific concepts such as security
alerts, incidents, LLM models, VRAM, employee scheduling semantics, logistics
routes, or financial portfolios. Those belong in external **domain adapters**.

## Architecture

```text
external domain project
         ↓
   DomainAdapter
         ↓
   VariaQ generic problem
         ↓
   VariaQ solver/backend
         ↓
   VariaQ generic result
         ↓
   DomainAdapter
         ↓
   project-specific result
```

A domain adapter is a small piece of code in an external package that:

1. translates project objects into a VariaQ `ProblemInstance`,
2. invokes a VariaQ solver,
3. maps the normalized `SolveResult` back into project terms.

The adapter owns the project-to-VariaQ mapping. VariaQ owns correctness of the
generic problem, evaluation, and solver execution.

## Current families

### MaxCut

The original reference family: partition graph nodes into two sets to maximize
(or minimize) total weight of edges crossing the partition. This remains the
family used for matched QAOA experiments.

### Assignment

Generic assignment of tasks to resources:

- opaque task IDs and resource IDs,
- per-pair score or cost,
- optional prohibited assignments,
- optional resource capacities,
- optional per-task demand (default 1),
- canonical objective: `Σ score[t,r] * x[t,r]`.

Example external uses: jobs to machines, tickets to agents, workloads to
servers, tasks to workers. The adapter maps the project vocabulary into the
neutral `task_ids`/`resource_ids`/`score` model.

### Subset Selection

Generic bounded subset selection:

- opaque candidate IDs,
- per-candidate value/score,
- optional per-candidate cost,
- optional total budget,
- optional minimum/maximum cardinality,
- optional pairwise interaction terms,
- canonical objective: `Σ score[i] * x[i] + Σ interaction[i,j] * x[i] * x[j]`.

Example external uses: experiment selection, feature selection, evidence
selection, test selection. The adapter decides what a "candidate" represents.

### Graph Partitioning

Generic weighted graph partitioning:

- opaque node IDs,
- weighted undirected edges,
- requested partition count `k ≥ 2`,
- optional per-partition size bounds,
- canonical objective: minimize total weight of edges crossing partitions.

The initial implementation supports any `k`. The adapter maps project graph
objects into neutral node/edge identifiers.

## Problem artifact format

A saved problem is a JSON document with:

- `schema_version: 1` — the problem artifact format version (independent of
  VariaQ package version and output schema version).
- `problem_id` — deterministic hash of canonical content.
- `problem_type` — family-specific identifier.
- `family` — one of `maxcut`, `assignment`, `subset-selection`,
  `graph-partition`.
- `sense` — `maximize` or `minimize`.
- `data` fields specific to the family.
- `generation` — provenance metadata (method, seed, parameters).

Problem IDs are deterministic: two semantically identical problems produce the
same ID even if dictionary key order differs.

## Objective sense

Every problem declares its objective sense. VariaQ uses it when:

- comparing results,
- computing optimality gaps,
- computing approximation/normalized ratios,
- ranking solutions during exact and heuristic search.

Do not assume every problem is maximization. A minimization gap is computed
relative to the best-known minimum, not by negating objectives.

## Solver support matrix

| Solver       | MaxCut | Assignment | Subset Selection | Graph Partition |
|--------------|--------|------------|------------------|-----------------|
| exact        | yes    | yes        | yes              | yes             |
| heuristic    | yes    | yes        | yes              | yes             |
| qaoa         | yes    | no         | no               | no              |
| cudaq-cpu    | yes    | no         | no               | no              |
| cudaq-gpu    | yes    | no         | no               | no              |

Unsupported solver/family combinations raise a structured `ValidationError`
before execution.

## Binary quadratic lowering

Each family can optionally be lowered to a backend-neutral binary quadratic
model. The lowered representation contains:

- `variable_ids`: one identifier per binary variable,
- `linear`: linear coefficients,
- `quadratic`: quadratic coefficients keyed by variable pairs,
- `offset`: constant term,
- `sense`: objective sense,
- `penalty_metadata`: explicit penalty coefficients and source family,
- `decode`: mapping from variable index back to semantic role.

A low-energy QUBO state is **not** automatically a valid domain solution. The
workflow is:

1. solve or sample the lowered model,
2. decode the binary state,
3. call `problem.evaluate(decoded_state)`,
4. report only if the solution is feasible.

Penalties are derived from problem data, recorded in `penalty_metadata`, and
documented in code.

## Domain adapter API

External packages can use the public surface:

- `variaq.adapter.DomainAdapter` — implement `to_variaq()` and `from_variaq()`.
- `variaq.adapter.AdapterResult` — returned by `from_variaq()`.
- `variaq.adapter.adapter_context()` — normalize a private mapping into JSON-safe
  context.
- `variaq.problems.*` — constructors for generic problem families.
- `variaq.solvers.get_solver()` and `variaq.models.SolverConfig` — run solvers
  programmatically.

Adapters are not registered with VariaQ. Import the interface and implement it
in your own package.

## Scaffolding

The CLI can scaffold a tiny adapter template:

```bash
variaq adapter init my-adapter --family assignment
```

This creates:

```text
my-adapter/
├── adapter.py
├── test_adapter.py
└── README.md
```

The generated code contains no project-specific or downstream-project names.
It must be edited to implement `to_variaq()` and `from_variaq()` for your
domain.

## Compatibility

VariaQ is pre-1.0. The machine-readable CLI schema version remains `"1"` and the
problem artifact format version remains `1`. The Python API surface is
intentionally small but may evolve; downstream projects should pin a VariaQ
version and validate the schema version in JSON output.
