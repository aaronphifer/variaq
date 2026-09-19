# Contributing to VariaQ

VariaQ welcomes focused, reproducible contributions. It is pre-1.0, so discuss
large API changes before substantial implementation work.

## Setup and checks

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev,quantum]'
```

On Windows PowerShell, activate the environment with
`.venv\Scripts\Activate.ps1`. Installing the base package and then adding
`pytest`, `ruff`, and `build` individually is not sufficient for the full test
suite: shared QAOA tests require NumPy, and Qiskit tests require the `quantum`
extra. NumPy remains optional for base exact and heuristic use.

CUDA-Q is optional:

```bash
python -m pip install -e '.[dev,quantum,cudaq]'
```

Normal tests require no credentials, network, GPU, or QPU. CUDA-Q integration
tests skip when it is absent.

```bash
pytest
ruff check .
ruff format --check .
python -m build
```

Use `ruff format .` to format. Do not commit databases, credentials, virtual
environments, build output, or local artifacts.

## New solvers

A solver must return a normalized `SolveResult`, reject unsupported or unsafe
requests clearly, use the authoritative problem evaluator, record seed/backend/
versions/timing, structure failures, and avoid hidden network or QPU execution.

Quantum solvers should include, where applicable:

- tiny independently known problems;
- fixed-parameter expectation checks;
- sign and rotation-angle validation;
- canonical bit-order tests;
- reproducibility metadata;
- optional-dependency and unavailable-backend tests.

Unsupported performance or advantage claims must not be presented as fact.
Distinguish simulator, hardware, cold-start, and warmed results.

## New problem families

Provide canonical serialization and identity, optimization sense, pure
evaluation and feasibility, deterministic generators or loaders, tiny known
cases, and solver-independent tests. Keep application-specific concepts in
external adapters.

## Pull requests

Keep changes reviewable. Explain what changed, why, tests run, whether solver
semantics changed, and whether any network or remote execution is involved.
