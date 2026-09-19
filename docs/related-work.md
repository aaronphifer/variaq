# Related work

VariaQ overlaps with established quantum optimization, benchmarking, and
hybrid-computing projects. This is not a claim that VariaQ is first or unique.

## Luna Quantum

[Luna Quantum](https://docs.aqarios.com/home/luna_welcome/) is an integrated
platform for building, benchmarking, and deploying quantum-powered optimization
applications. VariaQ currently has a smaller local-first scope centered on
explicit classical baselines, local artifacts, and controlled simulator
comparisons.

## OpenQAOA

[OpenQAOA](https://openqaoa.entropicalabs.com/) is a multi-backend QAOA SDK
with configurable parameterizations, optimizers, devices, and plugins. VariaQ's
QAOA layer is narrower: it owns one matched candidate search so adapters receive
identical vectors, within a broader classical/quantum experiment model.

## QED-C application-oriented benchmarks

The [QED-C benchmark
suite](https://github.com/SRI-International/QC-App-Oriented-Benchmarks)
evaluates systems through scalable application-oriented circuits and quality,
timing, and resource metrics. VariaQ similarly values application outcomes but
currently emphasizes local problem artifacts, independent evaluation, and
matched optimization inputs.

## MQT Bench

[MQT Bench](https://mqt.readthedocs.io/projects/bench/en/latest/) provides a
configurable quantum-circuit benchmark set across abstraction and compilation
levels. VariaQ instead currently measures end-to-end solver outcomes and
experiment lineage.

## QAOAKit

[QAOAKit](https://github.com/QAOAKit/QAOAKit) provides preoptimized parameters,
circuit generators, and reproducible QAOA research workflows. Its datasets and
QAOA focus complement VariaQ's backend-matched harness and normalized
classical/quantum result model.

## D-Wave Ocean

[D-Wave Ocean](https://docs.dwavequantum.com/en/latest/ocean/index.html)
provides modeling and solver tools for quantum, hybrid, and classical annealing.
VariaQ has no annealing adapter yet. Any future adapter must preserve
independent evaluation, metadata, and explicit remote authorization.

## openQSE and QFw

The [openQSE reference architecture](https://arxiv.org/abs/2604.20912)
addresses interoperable quantum-HPC stack boundaries. The [Quantum Framework
(QFw)](https://arxiv.org/abs/2509.14470) explores modular HPC-aware
orchestration across simulators and backends. These operate at a broader systems
level than VariaQ 0.2 and may eventually complement its experiment boundaries.

## VariaQ emphasis

- local-first, self-hostable workflows;
- reproducible artifacts and append-only lineage;
- identical cross-framework variational inputs;
- solver-independent evaluation;
- domain-neutral adapters;
- explicit negative and unavailable results;
- eventual heterogeneous CPU/GPU/authorized-QPU experiments.
