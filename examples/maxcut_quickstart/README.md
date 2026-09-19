# Deterministic MaxCut quick start

```bash
python -m pip install -e '.[quantum]'
./examples/maxcut_quickstart/run.sh
```

The script generates one deterministic 8-node graph, runs exact enumeration,
seeded local search, and Qiskit statevector QAOA, then lists the local records.
It needs no credentials or network and cannot use a physical QPU.

Pass an alternate output directory as the first argument. The default
`data/examples/maxcut_quickstart` is ignored by Git.

With CUDA-Q installed:

```bash
variaq --db data/examples/maxcut_quickstart/runs.sqlite3 \
  compare quantum data/examples/maxcut_quickstart/problem.json \
  --solvers qaoa,cudaq-cpu \
  --p 1 --optimizer-trials 32 --shots 1024 --seed 42
```
