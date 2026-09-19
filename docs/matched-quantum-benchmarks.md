# Matched quantum benchmark methodology

## Purpose

VariaQ compares quantum software stacks, not just plausible-looking QAOA implementations. A valid
comparison controls the experiment inputs and independently verifies the outputs. It does not
claim quantum advantage or general framework superiority.

## Controlled variables

For every matched repeat, VariaQ holds constant:

- exact weighted MaxCut graph;
- positive objective convention;
- |+⟩ initial state;
- QAOA depth `p`;
- cost and mixer Hamiltonians;
- gamma/beta angle and rotation conventions;
- parameter ordering;
- complete candidate parameter sequence;
- candidate ordering and shared ranking rule;
- candidate count;
- shot budget;
- repeat seed where backend seeding exists;
- final canonical objective evaluator.

The runner stores every candidate vector and a SHA-256 digest. Each backend stores its expectation
for every candidate and the selected index. `variaq compare quantum` reports candidate-digest
agreement and the maximum expectation delta.

## Verified v0.2 equivalence result

For the deterministic 8-node, 15-edge MaxCut instance generated with edge probability `0.4`
and seed `42`, Qiskit statevector and CUDA-Q `qpp-cpu` both found objective `12` using `p=1`,
32 matched candidates, and 1,024 shots. The maximum expectation difference was:

```text
2.842170943040401e-14
```

Depth-two checks differed by no more than approximately `5.77e-15` in the verified cases. This
validates numerical equivalence of the tested implementations within floating-point tolerance.
It does not show quantum advantage, hardware performance, or equivalence outside those cases.

## Conventions under test

Parameters are ordered:

```text
[gamma_0, ..., gamma_(p-1), beta_0, ..., beta_(p-1)]
```

For edge weight `w`, Qiskit `RZZ(-gamma*w)` and CUDA-Q
`CX-RZ(-gamma*w)-CX` both implement the non-global portion of
`exp(-i*gamma*w/2*(I-ZZ))`. Mixers use `RX(2*beta)`.

The test suite checks:

- a one-edge analytical result
  `E[C] = 1/2 + 1/2 sin(4 beta) sin(gamma)`;
- zero-angle and simple pi-based vectors;
- seeded vectors;
- p=1 and p=2;
- weighted multi-edge graphs;
- Qiskit/CUDA-Q agreement at FP64 tolerance.

These cases are designed to catch Hamiltonian sign and factor-of-two errors, not merely confirm
that both methods return feasible cuts.

## Bit ordering

VariaQ canonical order is variable 0 through variable n-1.

- Qiskit adapter: statevector integer bit `i` is variable `i`.
- CUDA-Q adapter: returned q0-first string character `i` is variable `i`.

Tests use an asymmetrically weighted graph where reversing `100` changes the objective, preventing
a reversed yet feasible assignment from passing unnoticed.

## Expectations versus samples

Ideal expectation evaluation is the strongest cross-framework equivalence signal because the
candidate vectors and objective are identical. Final sampled solutions can vary because Qiskit
and CUDA-Q use different random-number implementations. VariaQ therefore compares:

1. every candidate expectation;
2. selected candidate index and parameters;
3. sampled best objective and optimum gap;
4. repeated-run stability.

Substantial FP64 expectation differences require investigation. Tiny floating-point differences
within the documented tolerance are not treated as algorithmic differences.

## Timing protocol

Cold and warmed data must remain distinguishable:

- cold: no explicit warm-up; first-use effects remain in normal timing;
- warmed: one explicit first-candidate expectation occurs before the measured search and is
  reported separately, while still remaining in total wall time;
- repeated: each run is persisted independently with its own timing layers.

Do not conclude that GPU acceleration helps from one tiny cold circuit. Compare multiple sizes,
include warmed repeats, and inspect initialization separately from expectation and sampling time.

## Scaling and safety

The opt-in scaling matrix uses 4, 6, 8, 10, 12, 14, and 16 variables. Statevectors require
approximately `2^n` complex amplitudes—8 bytes each in FP32 complex form and 16 in FP64. VariaQ
records this estimate, applies variable/byte guards, and persists failures rather than crashing
the remaining suite.

Peak process or device memory is recorded only when a trustworthy low-overhead source is
available. Missing memory telemetry is not fabricated.

## Interpretation

All current backends are classical simulators. Faster simulation means a classical software or
hardware stack simulated the circuit faster; it does not demonstrate quantum advantage. Exact
and heuristic classical baselines remain mandatory in the full matrix.

CUDA-Q NVIDIA support is implemented, but the v0.2 host reported zero compatible devices and no
usable `nvidia-smi`. No GPU performance result is claimed. Unsupported GPU requests produce an
`unavailable` capability record rather than a failed experiment.
