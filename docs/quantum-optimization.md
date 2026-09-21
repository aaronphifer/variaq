# Quantum optimization in VariaQ

VariaQ 0.5 uses a single generic QAOA pipeline for all quantum-enabled problem
families. The pipeline is deliberately local, simulator-only, and transparent.

## Pipeline

```text
Original problem
      ↓
lower_to_binary_quadratic()
      ↓
BinaryQuadraticModel
      ↓
build_qaoa_problem()
      ↓
Generic QAOA layer
      ↓
Qiskit  or  CUDA-Q CPU/GPU
      ↓
Sample counts
      ↓
decode_bits()
      ↓
problem.evaluate()
      ↓
Normalized SolveResult
```

The original problem is authoritative at every step that matters: decoding,
feasibility, objective, and constraint violations.

## Matched cross-framework comparison

`variaq compare quantum` holds constant:

- the original problem instance
- the lowered BQM and its digest
- canonical variable ordering
- objective convention
- penalty configuration
- QAOA depth `p`
- candidate parameter vectors and their ordering
- seed (where the backend supports it)
- shots
- decoder
- final authoritative evaluator

The command now works for any family supported by the selected quantum solvers;
it does not hardcode `maxcut`.

## Infeasible samples

Quantum/BQM samples may decode to infeasible domain solutions. VariaQ handles
this explicitly rather than silently discarding them:

- `feasible_sample_count` and `infeasible_sample_count`
- `best_solution_energy` from the best feasible sample
- `best_infeasible_energy` from the lowest-energy infeasible sample
- aggregated constraint violation messages

If no feasible sample is found, the run status is `failed` and the result
reports a structured partial outcome.

## Resource guards

Before executing a quantum simulation, VariaQ estimates:

- binary/qubit count
- statevector size in bytes
- requested floating-point precision

If the estimate exceeds a configured guard (512 MiB for Qiskit, 2 GiB for
CUDA-Q by default), the solver returns a structured `SolverLimitError` instead
of exhausting memory. The guard can be lowered via `max_statevector_bytes` for
CUDA-Q; Qiskit uses a fixed conservative limit.

## Limitations

- All quantum execution is local ideal simulation. No physical QPU is invoked.
- Performance claims are measurements only; no quantum-advantage claim is made.
- Non-MaxCut families may require many binary variables and may not reach the
  global optimum with shallow QAOA.
- CUDA-Q GPU execution depends on compatible NVIDIA hardware and drivers.

## CLI examples

```bash
variaq problem generate maxcut --nodes 8 --edge-probability 0.5 --seed 42 \
  --output /tmp/mc.json

variaq solve /tmp/mc.json --solver qaoa --seed 1 \
  --param p=1 --param optimizer_trials=8 --param shots=128 --json

variaq compare quantum /tmp/mc.json --solvers qaoa,cudaq-cpu --p 1 \
  --optimizer-trials 8 --shots 128 --seed 1 --json

variaq problem generate assignment --task-count 4 --resource-count 3 --seed 1 \
  --output /tmp/assign.json

variaq benchmark /tmp/assign.json --solvers exact,qaoa,cudaq-cpu --seed 1 \
  --solver-param qaoa.p=1 --solver-param qaoa.optimizer_trials=8 \
  --solver-param qaoa.shots=128 --solver-param cudaq-cpu.p=1 \
  --solver-param cudaq-cpu.optimizer_trials=8 --solver-param cudaq-cpu.shots=128 \
  --json
```
