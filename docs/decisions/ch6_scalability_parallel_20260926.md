# Small real study: scalability and execution parallelism remain in scope

2026-09-26. The 48-query main study does not replace the scale, source-count,
candidate-count, or parallel execution experiments. This note freezes their
meaning and reuses existing preparations rather than adding another full pilot.

## Existing 21 figures

|Figure|Actual input levels|Fixed controls|Current preparation|
|---|---|---|---|
|S1|16, 64, 256, 1024 distinct candidate queries|D=2, same source and initial field count, explicit caps|`ch6_factor_inputs` already creates distinct finite families; D1 input and deployment pins exist|
|S2|2, 4, 8 actual endpoints|Same logical facts, complete query, aggregate CPU/RAM|D1 materializations and query/reference bundles exist; D2/D3 deployment variants remain to prepare|
|S3|.25, 1, 4 actual graph scale|Two sources, same query and cache protocol|D1 variants exist; .25 retains every fourth edge and all vertices, while 4 means four disconnected renamed replicas|
|S4|Same three actual graph scales|Same method/configuration/hardware|Measure coordinator peak RSS; do not multiply single-query memory by query count|

D1 factor artifacts are indexed by
`/Users/anthonyche/xgap-data/outputs/xgap-scalability-prep-20260926-v1/scalability-spec.json`
(SHA-256 `2dfabd96ac7c759f49e70de09c9729d1b08fea10c3b66dc2cc1ecc4a1734c7f3`).
The preparation script reads existing input specifications, not method outcomes.
These old factor configurations need the same live-probe configuration refresh
as the main study; existing successful loading does not imply probes were enabled.

Do not claim all three domains have these sweeps simply because the input
generator accepts them. D2/D3 source/scale service snapshots are still missing.
Do not turn N=1024 into 1024 copies of the same interpretation. Fixed-D polynomial
complexity does not imply polynomial dependence on D; depth remains a separately
measured hyperparameter. Resource-censored points remain in the result table.

## D4 synthetic stress supplement

The new `generate_ch6_synthetic.py` creates a source-only SQLite index compatible
with the existing core materializer, profile publisher, and independent SQL
reference engine. This index is offline data preparation, not the evaluated
query backend. Backend results must still come from actual graph services.

The frozen generator is `xgap-d4-ring-chords-v1`, seed 20260926, directed degree
8. It combines a directed ring with seven distinct modular chords, has no
self-loops, and has exactly eight incoming and outgoing edges per vertex.
All vertices have deterministic boolean `isMarked` attributes; edges have
explicit identity, timestamp and weight. No query, answer or measured method
performance influences data generation.

The first prepared size grid is:

|Scale|Vertices|Edges|RDF endpoints|
|---|---:|---:|---:|
|.25|16,384|131,072|2|
|1|65,536|524,288|2|
|4|262,144|2,097,152|2|

These are independently generated synthetic graphs at each size. They are not
four replicas of D1 and not empirical social or financial facts. The generator
and its recipe are implemented; the three large instances have not been
materialized or served in this turn. D4 source/scale results cannot be reported
until those services and independent reference outputs exist. It supplements
S1–S4 rather than replacing D1–D3 or adding new main figures.

The executable stages are source generation, `materialize_ch6_core.py` using
`--scale 1 --source-count 2` for each independent D4 graph, existing CPU service
preparation, and controlled factor input publication. Full command argument
pins for the runtime/trained profile come from the admitted server environment;
the recipe does not guess these paths or submit a job.

## Parallelism is a real execution knob

`FederatedScheduler.execute` already dispatches ready remote DAG nodes through
`ThreadPoolExecutor`, using `min(plan.max_parallelism, ready_remote_nodes)`.
Therefore 1/2/4/8 changes actual backend request concurrency when dependencies
permit it. It does not change the number of concurrent user queries, the number
of backend-internal threads, or the LLM request batch size.

The supplementary parallelism table fixes each method's previously selected
final plan, source snapshot, query artifacts, row/call limits and total allocated
CPU/RAM. Only `max_parallelism` changes. This is an execution-mechanism experiment,
not a new end-to-end planning result, and no measured candidate-plan race is used
to choose a plan. Report execution latency, observed peak in-flight requests,
actual calls/bytes, answer equality and coordinator RSS. Retain width-one chains:
their lack of speedup is an expected neutral control. Select plans by declared
query/DAG structure before observing parallel performance.

`xgap.experiments.ch6_parallel.execute` now performs the actual scheduler call
and records thread-safe request start/end intervals. It returns raw events and
observed peak overlap; a nominal flag alone is not an observation. The wrapper
is to run inside the existing guarded, observed source session, which retains
ownership of timeout handling and backend shutdown. It does not start services
or replace those safeguards.

XGAP/NP/SH/GR can each reuse their own frozen plan. TS has no admitted knob that
maps to this scheduler; retain its fixed original configuration reference and
mark the parameter inapplicable. Do not silently alter FedX/ARUQULA internals to
manufacture matching parallelism. No additional main figure is introduced:
the parallelism measurements are a supplementary table unless the user later
changes the figure plan.

## Verification and remaining work

Two focused tests passed: deterministic source identity/counts/degrees, and real
thread overlap increasing with parallelism while result rows and call counts
remain unchanged. Those tests use a tiny generated index and a fixture backend;
they are engineering verification, not paper measurements.

No model calls, remote queries, server materialization or Slurm submission were
performed. Immediate work is to connect these preparation artifacts to the
small-study server package, freeze the actual selected plan pins, and run each
predeclared real factor level once. D4 loading and D2/D3 scale variants remain
explicit tasks; they are not hidden behind a generic “ready” flag.
