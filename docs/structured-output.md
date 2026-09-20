# VariaQ structured output

VariaQ 0.3.0 introduces a first-class, versioned machine-readable CLI contract.
The goal is that shell scripts, CI systems, the `bb-plugin-variaq` adapter, and
future web/API layers can consume VariaQ without parsing tables or prose.

Human-readable output remains unchanged and is still the default.

## Schema version

VariaQ uses two independent version concepts:

- **VariaQ version** — the package release (e.g. `0.3.0`).
- **Output schema version** — the shape of machine-readable CLI output.

For VariaQ 0.3.x the output schema version is **`1`**. Future VariaQ releases may
bump the schema version when the output shape changes in a way that would break
existing consumers. The schema version is reported in every JSON response and by
`variaq capabilities`.

Compatibility policy:

- Within a schema version, field additions are allowed but removals or semantic
  changes that break documented consumers are not.
- A new schema version will be introduced explicitly; consumers should check
  `schema_version` before relying on newer fields.
- VariaQ is pre-1.0; the internal Python API is **not** stable. The
  machine-readable CLI schema has a stronger compatibility promise.

## Enabling JSON output

JSON output is requested with a per-subcommand `--json` flag:

```bash
variaq capabilities --json
variaq solve <problem-id> --solver exact --json
variaq benchmark <problem-id> --solvers exact,heuristic,qaoa --json
variaq compare quantum <problem-id> --solvers qaoa,cudaq-cpu,cudaq-gpu --json
variaq runs list --json
variaq runs show <run-id> --json
variaq runs reproduce <run-id> --json
variaq problem generate maxcut --nodes 8 --edge-probability 0.4 --seed 42 --json
variaq problem show <problem-id> --json
```

`--json` is accepted on every command that produces output. It is intentionally a
subcommand flag so that global options (`--db`, `--problems-dir`) keep their
existing positions.

## JSON output rules

When `--json` is used:

- `stdout` contains **valid JSON only**.
- No tables, progress prose, warning banners, ANSI formatting, or stack traces on
  `stdout`.
- Diagnostic information may go to `stderr` when appropriate.
- A caller should be able to run:

  ```bash
  variaq ... --json | jq .
  ```

- Nonzero exit codes are **preserved**; errors are not flattened to `0`.

## Envelope

Every JSON response is wrapped in one envelope:

```json
{
  "schema_version": "1",
  "command": "solve",
  "status": "success",
  "data": { ... },
  "warnings": []
}
```

```json
{
  "schema_version": "1",
  "command": "solve",
  "status": "error",
  "data": { ... },
  "error": {
    "type": "SolverLimitError",
    "message": "Exact solve refused 8 variables; configured guard is 2",
    "run_id": "run-..."
  },
  "warnings": []
}
```

### Status values

- `success` — the command completed and `data` contains the result.
- `partial` — at least one solver/operation failed but other results are still
  present (used by `benchmark` and `compare quantum` with mixed outcomes).
- `error` — the command could not produce a useful result.

### Error object

```json
{
  "type": "ValidationError",
  "message": "Problem not found: ...",
  "run_id": "run-...",
  "context": { ... },
  "retryable": false
}
```

- `type` — the Python exception class name (stable, no stack trace).
- `message` — a human-readable explanation.
- `run_id` — included if a failed run was persisted.
- `context` — optional structured context (e.g. the failing solver list).
- `retryable` — included only when it can be determined reliably.

### Warning object

```json
{
  "type": "backend_unavailable",
  "message": "CUDA-Q is installed, but no compatible NVIDIA GPU is available",
  "context": { "solver": "cudaq-gpu", "run_id": "run-..." }
}
```

## Command outputs

### `capabilities --json`

Reports VariaQ version, schema version, problem families, solvers with
`supported` / `installed` / `available` flags, framework versions, and CUDA-Q
target availability. Physical QPU execution is explicitly reported as unsupported.

Key fields:

- `variaq.version`
- `variaq.output_schema_version`
- `problem_families`
- `solvers[].{name,supported,installed,available,reason}`
- `frameworks` (Qiskit and CUDA-Q versions/targets)
- `physical_qpu.{supported,installed,available,reason}`
- `warnings`

### `solve --json`

Returns a single solver run:

- `run_id`
- `problem_id`, `problem_type`
- `solver`, `backend`, `backend_type`
- `status`
- `solution`, `objective`, `feasible`, `constraint_violations`
- `best_known_objective`, `best_known_source`, `optimality_gap_percent`,
  `approximation_ratio`
- `wall_time_seconds`, `solver_time_seconds`
- `seed`, `parameters`
- quantum fields when applicable: `qaoa_depth`, `shots`, `optimizer_trials`,
  `candidate_parameter_digest`, `selected_parameter_index`,
  `selected_parameters`, `expectation`, `qubit_count`, `circuit_depth`,
  `gate_count`, `logical_gate_count`
- `backend_metadata`
- `environment`
- `created_at`

### `benchmark --json`

Returns one coherent comparison object:

```json
{
  "problem": { ... },
  "runs": [ ... ],
  "comparison": {
    "aggregate_status": "success|partial|error",
    "best_known_objective": 12.0,
    "best_known_source": "exact_optimum",
    "solver_count": 3,
    "successful_count": 3,
    "failed_count": 0,
    "unavailable_count": 0
  }
}
```

Mixed solver outcomes do not make the whole response unusable. Individual failed
solvers appear in `runs` with `status: "failed"`, and the aggregate status becomes
`partial`.

### `compare quantum --json`

Extends the benchmark shape with matched-QAOA detail:

- `comparison.matched_qaoa`
- `comparison.qaoa_depth_p`
- `comparison.optimizer_trials`
- `comparison.shots`
- `comparison.seed`
- `comparison.candidate_parameter_digest`
- `comparison.identical_candidate_parameters`
- `comparison.max_expectation_delta`
- `comparison.best_parameter_indices`
- `comparison.precision`
- `comparison.backend_target`
- `comparison.unavailable`

This is the primary structured surface the plugin will use; it no longer needs
to scrape run IDs from prose.

### `runs reproduce --json`

Returns reproduction lineage:

- `original_run_id`
- `new_run_id`
- `rerun_of`
- `lineage`
- `original.{solver,problem_id,seed,parameters,environment,result}`
- `new.result` (full solve JSON)
- `environment_differences`

The original run is never overwritten.

### `runs show --json` and `runs list --json`

`show` returns the full public run record inside the envelope. `list` returns a
list of summary records. Both are normalized to the same envelope.

### `problem generate --json` and `problem show --json`

`generate` returns `problem_id`, `problem_type`, `node_count`, `edge_count`,
`seed`, and the saved `path`. `show` returns the full problem document.

## Exit codes

VariaQ preserves the existing exit-code contract:

- `0` — success (or `partial` with no hard failures, depending on command).
- `1` — solver/runtime failure (a persisted run failed, or at least one solver in
  a benchmark failed).
- `2` — usage/lookup/input error (missing problem, unknown run, invalid
  configuration).

In JSON mode a nonzero exit code is still accompanied by a structured envelope on
`stdout`.

## Reproducibility contract

A stored run preserves enough information to recreate the experiment where the
underlying implementation allows it:

- exact problem content and `problem_id`
- solver identity and configuration
- seed
- QAOA depth, trials, shots, warmup
- candidate parameter sequence / digest
- framework/backend and precision
- environment versions
- parent `rerun_of` lineage

Guarantees:

- **Strong reproducibility** for deterministic exact solvers, seeded heuristics,
  and ideal statevector under the same software semantics.
- **Best-effort reproducibility** for GPU execution across different
  hardware/driver versions. VariaQ does not claim bit-identical results where the
  underlying stack does not.

## Float handling

JSON output preserves scientific precision. Non-finite values (`NaN`, `Infinity`)
are rejected at serialization time and become structured errors. NumPy scalars and
paths are normalized to plain JSON primitives.

## Security

Structured output intentionally does **not** include:

- environment variables
- API keys or credentials
- home-directory secrets
- unrelated system configuration

Paths are surfaced only when clearly useful (e.g. the saved problem path from
`problem generate --json`).

## Future directions

- Optional formal JSON Schema definitions once the shape stabilizes.
- Additional problem families will extend `problem_families` and `data.problem`
  while keeping the same envelope.
- Physical QPU support, if added, will require explicit opt-in and will be
  reflected in `physical_qpu` and backend metadata, never as an accidental default.
