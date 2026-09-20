# VariaQ domain adapters

Domain adapters are the public boundary between an external project and VariaQ.
They keep domain semantics out of VariaQ core.

## Why adapters exist

VariaQ is intentionally domain-neutral. It knows about tasks, resources,
candidates, costs, graph nodes, edges, and partitions. It does not know about
cybersecurity alerts, employee schedules, logistics routes, or financial
portfolios.

An external project that wants to use VariaQ writes an adapter that:

1. receives project-specific objects,
2. builds a VariaQ generic problem instance,
3. asks VariaQ to solve it,
4. translates the normalized result back into project terms.

## Adapter contract

The public interface is `variaq.adapter.DomainAdapter`:

```python
from variaq.adapter import DomainAdapter, AdapterResult, adapter_context
from variaq.models import SolveResult
from variaq.problems.base import ProblemInstance


class MyAdapter(DomainAdapter):
    problem_family = "assignment"  # or "subset-selection", etc.

    def to_variaq(self, source) -> ProblemInstance: ...

    def from_variaq(self, result: SolveResult, context) -> AdapterResult: ...
```

`AdapterResult` carries:

- `result`: the project-specific translation,
- `context`: a JSON-safe mapping object (e.g. external ID ↔ VariaQ opaque ID).

Adapters are not registered with VariaQ. Implement the interface in your own
package and import VariaQ public classes.

## Preserving IDs

VariaQ preserves opaque string IDs in problem and result objects. An adapter can
keep a private dictionary, such as `{"task-1": "INC-2026-0001"}`, and return it
in `context`. This lets the project map VariaQ results back without embedding
domain metadata inside VariaQ's solver model.

## Example: task-to-worker assignment

A neutral example is provided in
[`examples/adapters/task_assignment/`](examples/adapters/task_assignment/).
It assigns generic `WorkItem` objects to `Worker` objects by skill match, using
the `AssignmentProblem` family.

The example contains no project-specific names. It demonstrates:

- building a score matrix from domain attributes,
- marking prohibited pairs,
- running an exact solver,
- decoding the binary solution back into `WorkAssignment` objects.

## Scaffolding a new adapter

```bash
variaq adapter init my-adapter --family assignment
```

This writes a minimal template in `my-adapter/`:

```text
my-adapter/
├── adapter.py
├── test_adapter.py
└── README.md
```

Edit `adapter.py` to implement `to_variaq()` and `from_variaq()` for your
project. The generated template imports only VariaQ public interfaces.

## Security

Problem artifacts and adapter inputs are data. VariaQ never evaluates Python code,
executes shell commands, or dynamically imports paths from problem files. Adapter
scaffolding writes source files only when explicitly requested and does not run
the generated code.

## Compatibility

VariaQ is pre-1.0. The public adapter surface is intentionally small, but the
Python API may change before 1.0. Pin a VariaQ version in your adapter package
and validate the CLI `schema_version` when consuming JSON output.
