# Scientific benchmarks: first v0.8 slice

The opt-in MaxCut suite uses the existing campaign, experiment history, analysis,
and reporting layers. It requires no optional packages for classical runs or for
the new core tests. All quantum backends in this suite are local simulators.
Numerical agreement and simulator timing do not demonstrate quantum advantage.

## Bounded suite

`benchmarks/maxcut_v0.8_unwarmed.campaign.json` and
`benchmarks/maxcut_v0.8_warmed.campaign.json` each request 90 runs:
3 sizes (4, 6, 8 nodes), 2 graph seeds (11, 42), 3 solver repeats, and 5 solvers
(exact, heuristic, Qiskit, CUDA-Q CPU, CUDA-Q GPU). They use edge probability 0.4,
solver seeds 42–44, depth 1, 8 identical candidates per matched repeat, 128 shots,
and FP64 for both CUDA-Q targets. Exact enumeration is guarded at 256 states;
heuristics use 4 restarts and 16 passes; CUDA-Q has a 1 MiB statevector guard.
Existing quantum variable/memory guards also apply. Execution is sequential.

These are **campaign files**, not legacy `variaq suite` instance files. The old
suite remains supported. Use `campaign plan` before running. A missing optional
package or GPU produces a durable `unavailable` run with its reason. A solver
exception produces a failed run; neither is scored as a feasible solution or as
successful performance. Skipped unsupported solvers have no experiment record.

```bash
variaq --db data/v08.sqlite3 campaign plan benchmarks/maxcut_v0.8_unwarmed.campaign.json --json
variaq --db data/v08.sqlite3 campaign run benchmarks/maxcut_v0.8_unwarmed.campaign.json --json
variaq --db data/v08.sqlite3 campaign run benchmarks/maxcut_v0.8_warmed.campaign.json --json
# Substitute the campaign_id returned by each run:
variaq --db data/v08.sqlite3 analyze campaign campaign-ID --compare paired_solvers \
  --include-failed --include-unavailable --json
variaq --db data/v08.sqlite3 report campaign campaign-ID --compare paired_solvers \
  --output-dir reports/v08
```

On Linux, prefix each campaign run with `timeout 120s` for an external hard wall
limit. Algorithm budgets bound work, but the synchronous runner cannot interrupt
a hung native backend call. Campaigns save each completed solver attempt before starting the next.
Interrupted execution retains completed attempts; an in-flight native call's
result may not have been saved. There is no automatic retry or native cancellation.
Do not run this optional quantum matrix in ordinary CI. For a core-only trial,
copy a campaign definition and retain only `exact`/`heuristic` and their overrides.

Identical existing problem files are checked and reused. Re-running a definition
appends new run IDs to the same deterministic campaign ID; benchmark IDs separate
execution batches. Use explicit run selection to analyze only one execution.

## Measurements and pairing

`--compare paired_solvers` adds `instances` to `AnalysisResult` and a comparison
through the existing `ComparisonSummary` model. It works independently of
`group_by`. Each instance contains the canonical problem, exact-reference run IDs,
per-run measurements, and repeat summaries. Original source records remain intact.

- Solutions are re-evaluated by the original problem. Reported solver objectives
  are retained separately, with an agreement flag.
- Optimality gaps require consistent feasible exact runs in the selected data.
  Best observed heuristic/sampled results never become proven optima. Absolute
  gaps respect minimize/maximize semantics. Percentage gaps divide by the absolute
  reference; equality gives zero, including a zero optimum (the existing
  convention). A nonzero gap with zero reference has null percentage and a reason.
- Pairing requires the same mathematical problem, benchmark ID, and repeat index.
  Historical records use configuration seed within the benchmark. Duplicate slots
  are ambiguous and remain unpaired. Standalone runs receive measurements but
  are not paired. Missing slots cannot distinguish skipped, filtered, or interrupted
  runs; this limitation is explicit rather than inferred.
- Numerical comparison requires identical QAOA candidates, budgets, warmup flags,
  and seeds, plus complete candidate expectations. It reports maximum expectation
  delta separately from sampled solution quality and durations. Precision is
  retained for interpretation; no universal tolerance or speedup is asserted.
- Wall time measures the complete solver call, including validation, lowering,
  setup/imports, and warmup; database writes and environment capture are excluded.
  Solver compute time uses each solver's reported scope. For quantum solvers this
  covers warmup, expectation evaluation, and sampling. Initialization, search,
  expectation, warmup, and sampling layers are retained when measured. Search and
  expectation times overlap and must not be added together.
- Unavailable measurements are null with `missing_measurements` reasons. Failed
  and unavailable attempt wall time is retained separately. Missing timing layers
  never become zero. An unrequested warmup has no measurement in paired analysis.
- Repeat summaries stay within an instance, solver/backend, requested configuration,
  and warmup mode. They include observation counts, mean, median, sample standard
  deviation, minimum, maximum, source IDs, and status counts. Standard deviation is
  null with fewer than two observations. Different seeds vary sampling/search;
  exact and heuristic results can remain deterministic.

`unwarmed` means no explicit warmup, so first-use costs remain in timing.
`explicit_warmup` performs the existing first-candidate warmup before search;
its cost remains inside wall/compute time and is reported separately.
Capability discovery imports dependencies and queries targets/devices without
executing a solver or selecting a CUDA-Q target. Imports/device discovery can still
initialize runtime state. `first_backend_evaluation_seconds` measures the first
expectation call, including lazy compilation/setup. It overlaps warmup (when
requested) or expectation evaluation (when unwarmed), so it must never be added
to those layers. CUDA-Q initialization separately covers imports, target selection
and kernel construction; it does not claim to isolate all first-use GPU costs.
The solver invocation index helps identify first use within the runner, but shared
process/backend/device caches prevent a verified GPU cold-start claim.
`cold_start_verified` is null with explanatory metadata. Separate CLI invocations
reduce process reuse but do not prove fresh GPU/driver state.

`compare quantum --json` now compares expectations within matched repeats instead
of comparing distinct repeat candidate sequences. With no complete backend pair,
its delta is null with a reason. Existing summary comparisons remain available;
use paired analysis for scientific per-repeat conclusions.

## Reporting and compatibility

The existing JSON and Markdown artifacts now include instance measurements,
pair observations, variability, and missing-data explanations. CSV exports add
`_runs.csv`, `_pairs.csv`, and `_repeats.csv`, retaining nested scalar fields and
encoding lists as JSON. Empty paired analyses emit header-only CSV files. Empty
CSV cells represent null; reasons are exported alongside measurements.

Ordering is deterministic. Report IDs now include analysis contents, so different
comparison/scaling requests cannot collide. A report freezes its generation time
across exports; a separately regenerated artifact can have a new generation time.
Run IDs, actual durations, environment versions, and timestamps naturally differ
between new benchmark executions. Reproducibility means controlled inputs and
traceable observations, not identical elapsed times or cross-backend samples.

CLI schema, campaign format, report format, and SQLite schema stay at version 1.
No migration or historical record rewrite is required. Missing older metadata is
handled conservatively. Percentage gaps without proven optima and incomplete
numerical comparisons now return null; consumers must handle these values.
The local API accepts `paired_solvers` and safely serves the new CSV filenames.
No remote execution, IBM hardware, credentials, or hosted services are added.

GPU precision now uses `nvidia` with an explicit precision option, following
[NVIDIA's target documentation](https://nvidia.github.io/cuda-quantum/latest/using/backends/sims/svsims.html).
This avoids the deprecated `nvidia-fp64` alias's native stdout warning, which would
otherwise contaminate CLI JSON. Historical backend names stay in their source records.

## Audit and follow-up

Reused: canonical problem IDs/evaluators, exact and heuristic solvers, generic BQM
lowering, matched candidate generation/digests, backend capability discovery,
quantum memory guards, layered timers, append-only experiment history, campaign
planning/execution/membership, statistical summaries, and JSON/CSV/Markdown exports.
Existing tests already cover solver limits, Hamiltonian/bit ordering, cross-backend
equivalence, structured CLI output, historical data, and web security.

This slice adds deterministic campaign fixtures, reliable pairing and reference
quality, missing-data semantics, provenance, repeat statistics, and regression
coverage. The local web comparison workspace now exposes these analysis/API fields:
instance selection, timing scopes, warmup modes, missing reasons, quality versus
numerical agreement, and paired variability. See [web benchmarking workflow](benchmarking-ui.md). Fresh-process cold
start measurement, peak memory telemetry, confidence intervals, and hard native
backend cancellation remain deferred. Durable task interruption recovery is implemented
as described in [candidate hardening](releases/v0.8.0-hardening.md).
