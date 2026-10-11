# Scientific benchmarking in the local web UI

This is the unreleased `0.8.0rc1` candidate;
CLI, API, campaign, report, and SQLite versions remain compatible with schema 1.
Start the existing loopback web service with the web extra installed:

```sh
variaq --db data/variaq.sqlite3 web
```

The dashboard offers **New Experiment** and **Compare Results**. “Fully recorded
campaigns” counts campaign memberships meeting the definition's requested run
count; it includes failed attempts and reruns. This is not durable execution-state
or successful-solve accounting. Recent activity and capability availability are
separate: a historic GPU result can exist when today's GPU is unavailable.
All quantum backends currently shown are local simulators; no physical QPU or
quantum advantage is established.

## Plan and run

Choose a problem family and a deterministic generated reference recipe, then
select compatible, currently available solvers. Problem seeds define mathematical
instances; solver seeds control search and sampling. Classical exact and heuristic
solvers are the initial defaults. The small recipe uses size 6 and problem seed 11;
the scaling recipe uses sizes 4, 6, 8 and problem seeds 11, 42. Canonical problem IDs
are recorded on execution. This workflow generates reference instances; it does not
import an arbitrary filesystem path or directly select an existing problem file.

Advanced controls expose generator parameters and shared QAOA depth, candidates,
shots, explicit warmup and CUDA-Q GPU precision (CPU remains FP64). The existing campaign solver overrides
carry these values into the runner. Review the execution plan's work counts,
availability, exact enumeration, and estimated simulator resources before starting.
Any setup edit invalidates the reviewed plan. A plan is not a guarantee that an
optional backend remains available when execution starts.

One in-process execution slot is shared by campaigns and reproductions. Recorded
progress counts persisted attempts, including unsuccessful outcomes; skipped work
can leave that count below the plan. Refreshing the experiment form can reconnect
to the last browser-tracked task. SQLite snapshots survive server restarts and
unfinished tasks become `interrupted`, with saved run counts and an explanation.
An OS-held worker lock prevents a second web worker from executing on the same
database. Duplicate web submissions reconnect to the original task, including
terminal tasks, and never retry automatically. Historical campaign definitions
without a journal are refused for execution because their state is uncertain.
Inspect preserved evidence before explicitly creating a new campaign with a
different name. Explicit CLI reruns still append a new execution; they cannot
resume an interrupted native operation.

## Compare evidence

Choose a campaign or up to 500 explicit run IDs. The comparison API analyzes at
most 500 matching records in a window, with visible total, offset and next/previous
controls. Solver, backend and instance filters apply in the database. Size and
warmup filters apply within that labelled window. Large campaign windows can split
repeat pairs; focus an instance to inspect a smaller compatible selection.

Objective and gap charts display one explicitly named instance. The comparison
summary shows its selected exact optimum, valid quality-run count, optimum-achievement
rate and mean measurable gap. Achievement counts only successful feasible evaluated
runs with a consistent reference (including selected exact runs), using the existing
quality tolerance of 1e-9. Its numerator/denominator is visible. Undefined relative
gaps have a separate denominator; a nonzero absolute gap to a zero optimum has
no percentage. Measured zero gaps show a labelled baseline dot and explicit counts;
unavailable gaps remain absent and labelled unavailable.

Quality and timing charts show Python descriptive means per solver/backend,
configuration, precision, warmup mode, benchmark execution, environment and timing
scope. Successful infeasible or unevaluable runs do not enter these summaries.
Chart focus and evidence-instance filtering are separate controls. Changing chart
focus does not silently narrow the other filters or exported selection. Quality,
gap and timing charts show at most 12 configurations, with an explicit notice when
further configurations
remain in the complete summary tables. Comparison configurations use C labels;
existing scaling series use separate S labels.
Source IDs, full controls and individual measurements remain available; grouping
does not establish matched experimental controls or change recorded pairing.
Seeds/candidate angles can vary across repeats under the same configured budget.
Long methodological explanations are available under “How to read these comparisons.”
Only feasible objectives enter the quality chart. References come from consistent feasible exact
runs in selected evidence. Filtering out exact runs can make gaps unavailable;
that is reported with a reason, not converted to zero. Wall, compute and explicit
warmup charts retain nulls and use seconds. Failed attempt duration is separate
from successful performance. Historical timing scopes can remain unknown.

Scaling retains existing Python repeat timing means (successful timing observations
can include infeasible solutions); it shows them separately for each problem
instance, solver, backend, configuration and warmup mode. Different instances remain distinct points,
with identity in tooltips and accessible data tables. No quality is pooled across
instances and no speedup ratio is inferred. Repeat tables expose count, mean,
median, sample standard deviation and range; fewer than two observations have no
standard deviation. These are not confidence intervals.

A recorded pair shares problem identity, benchmark execution and repeat slot.
Failed paired records are labelled; absent or duplicate slots remain incomplete or
ambiguous. Standalone runs remain unpaired. Candidate-expectation agreement is
reported only when Python's existing controlled-pair rules allow it.

The complete selected window (not just the currently displayed instance) exports
through the existing report layer to JSON, CSV and Markdown, with source IDs,
measurements, pairing, variability and missing reasons. A report of the same
selected evidence retains its artifact generation timestamp when regenerated.
Known filenames and report-root confinement govern downloads and comparison
exports; planted output symlinks are refused. No filesystem or shell selector is
provided to the browser.

## Inspect and reproduce

Run detail shows authoritative re-evaluation against up to 500 explicitly selected
runs of the same problem, including exact reference source IDs and missing reasons.
Original reported measurements remain labelled separately. Expand the canonical
problem, solver configuration, environment, timing scopes, warnings and lineage.
Eligible local reproductions use the existing runner and append a linked new run;
wall times and sampled outcomes are not expected to be identical.

Charts have data tables, numbered observations or distinct point shapes, explicit
units, readable legends and keyboard-accessible explanations. Narrow comparison
tables become labelled cards; optional historical data tables scroll within their
containers. Tooltip help can be dismissed with Escape.

Remaining measurement work includes verified GPU cold starts, trustworthy
peak-memory telemetry, confidence intervals, native-call cancellation and manual
assistive-technology review. Durable interrupted-task recovery is implemented;
see [candidate hardening](releases/v0.8.0-hardening.md). No hosting, remote worker,
scientific schema migration or published release is part of this candidate.
