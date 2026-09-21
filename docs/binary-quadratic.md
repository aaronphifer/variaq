# Binary Quadratic Model

VariaQ 0.5 introduces a backend-neutral **Binary Quadratic Model (BQM)** as an
optional artifact for quantum and combinatorial solvers. The BQM is *not* the
source of truth: the original problem instance remains authoritative for
feasibility, objective evaluation, decoding, and constraint violations.

## Energy convention

The BQM represents an objective over binary variables `x_i ∈ {0, 1}`:

```text
E(x) = offset
       + Σ_i linear[i] * x_i
       + Σ_{i < j} quadratic[i, j] * x_i * x_j
```

The BQM objective is always optimized in the direction of the source problem
sense:

- `maximize` -> higher BQM energy is better
- `minimize` -> lower BQM energy is better

For unconstrained problems the BQM energy equals the source objective. For
constrained problems, penalty terms are added with a sign that makes infeasible
assignments worse than any feasible assignment:

- maximize problem: penalties *subtract* from energy when violated
- minimize problem: penalties *add* to energy when violated

This convention preserves VariaQ's established MaxCut QAOA numeric behavior:
the QAOA expectation for a MaxCut instance is the expected cut weight.

## Structure

The BQM is implemented as an immutable dataclass in `variaq.bqm`:

- `variable_ids`: ordered tuple of opaque identifiers
- `linear`: linear coefficient per variable_id
- `quadratic`: coefficients keyed by canonical ordered pairs `(i, j)` with `i < j`
- `offset`: constant term included in expectation values
- `sense`: source problem sense (metadata only)
- `source_family`, `source_problem_id`: provenance
- `penalty_metadata`: explicit penalty values and derivation notes
- `decode`: per-variable metadata mapping bits back to domain roles

Validation rejects duplicate identifiers, quadratic self-terms, unknown
variable references, non-finite coefficients, and malformed decode mappings.

## Lowering

Each supported family provides a lowering in `variaq.lower.lower_to_binary_quadratic`:

- **MaxCut** — one binary variable per node; BQM energy equals cut weight.
- **Assignment** — one-hot encoding per task; penalties enforce task assignment,
  prohibited pairs, and resource capacities.
- **Subset Selection** — one binary variable per candidate; penalties enforce
  budget and cardinality bounds.
- **Graph Partitioning** — one-hot encoding per (node, partition); penalties
  enforce one partition per node and optional balance constraints.

Penalties are derived deterministically from problem magnitudes and recorded
in `penalty_metadata`. They can be overridden by an optional future configuration
field; in 0.5 the defaults are fixed.

## QAOA use

Solvers receive a `QAOAProblem` built from the BQM:

```text
problem -> BQM -> QAOAProblem -> Qiskit / CUDA-Q -> samples -> decode -> evaluate
```

The QAOA layer does not know about budgets, partitions, or graph cuts. It only
knows the number of binary variables, the cost Hamiltonian coefficients, the
QAOA depth `p`, and the candidate parameter vectors. Backends map variable ids
to qubit indices with `variable_ids.index(var_id)` so non-contiguous or
non-integer identifiers are safe.

## Decoding and evaluation

After sampling, each binary vector is passed back through `bqm.decode_bits`
and then evaluated by the original problem instance. The solver reports:

- decoded solution
- feasibility and constraint violations
- authoritative objective
- best feasible and best infeasible sample energies
- feasible/infeasible sample counts

Do not report raw QAOA expectation as the final problem objective.
