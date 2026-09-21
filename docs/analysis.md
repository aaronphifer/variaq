# Analysis

The VariaQ 0.6 analysis layer consumes stored run records and produces
structured, domain-neutral summaries.

It answers questions such as:

- How does objective quality change with problem size?
- How does heuristic performance compare with exact?
- How does QAOA feasibility vary?
- How do runtimes scale?

## Analysis model

Key public types:

- `AnalysisQuery` — what runs to include and how to group them.
- `AnalysisResult` — groups, scaling points, comparisons, warnings, source run IDs.
- `GroupSummary` — quality, feasibility, timing, resource, and environment stats for a group.
- `ScalingPoint` — a group summary keyed to an explicit x metric.
- `ComparisonSummary` — classical-vs-quantum, Qiskit-vs-CUDA-Q, CPU-vs-GPU.

## Grouping and filtering

Groups are formed from run-record fields:

- `family`, `problem_id`, `solver`, `backend`, `seed`
- `status`, `feasible`
- `qaoa_depth`, `shots`, `optimizer_trials`, `precision`
- `variaq_version`, `qiskit_version`, `cudaq_version`, `python_version`
- `backend.metrics.<key>` and `parameters.<key>`

## Quality metrics

Quality summaries respect `OptimizationSense`:

- best/worst objective
- mean/median objective
- mean gap percent to best-known objective
- success-at-optimum rate
- approximation ratio where mathematically valid

For maximize families higher is better; for minimize families lower is better.

## Feasibility metrics

- feasible/infeasible run counts
- feasible/infeasible sample counts
- mean/median/min/max feasible sample rate
- zero-feasible-run count
- best feasible objective
- best infeasible energy where available

## Timing metrics

- total wall time
- solver/kernel time
- initialization, parameter search, expectation evaluation, sampling, warmup
  (when backend metadata provides them)

Timing scopes are labeled; mismatched scopes are not compared.

## Resource metrics

- logical variables
- binary variables
- qubits
- estimated statevector bytes
- circuit depth and gate count (when available)

## Repeat statistics

- count, mean, median, std, min, max
- std is omitted for single observations

## Historical compatibility

Analysis works on v0.1–v0.5 run records. Missing newer fields become `null`
rather than invented zeros.
