# Baseline fidelity

Authority: user instruction on 2026-09-12: “不要帮baseline方法优化结果”.
Further clarification: “baseline方法只要能跑起来就行了，如实反映结果”.
Operational readiness means the original method runs and produces auditable
answers/failures/costs. It does not require passing every correctness query.
Do not turn a baseline's wrong answer or unsupported operator into a development
blocker or repair task. The current native FedUP and FedX entrypoints both meet
that operational threshold; their differing results remain measured outcomes.

Pin the author implementation and disclose its settings. Environment preparation,
dependency compatibility and faithful transport adapters are permitted; changing
the method to improve its results is not. Do not repair its optimizer, add missing
operators, rewrite answers, tune from evaluation outcomes, choose an execution
engine per question or retry for a better answer. Required native internal retries
remain visible and charged; the outer harness submits each declared run once.

Unsupported queries, incorrect answers and execution failures stay in the declared
population with their raw outputs. A result normalizer may implement a prespecified
equivalence contract, but cannot reorder ordered answers or remove bag duplicates
to make a method pass. Source errors are recorded alongside HTTP 200/partial/empty
results; these are not counted as verified successful executions.

Do not confuse an error in our environment/adapter with a limitation of the
original method. Correct such integration defects before formal evaluation and
preserve their diagnostic records. Likewise, do not deliberately use a faulty
installation or unsupported setting to make XGAP appear stronger. Shared-support
efficiency and whole-workload capability/quality are different claims. Any reduction
of the agreed workload or replacement of a method remains an explicit research
decision, never a silent deletion of failed cases.

## Immediate application

The common HTTP observer initially forwarded client HTTP/2-upgrade fields onto an
HTTP/1.1 upstream hop; this caused FedUP ASK HTTP 400 responses. Removing hop-local
headers is a transport compatibility correction, not a FedUP optimization. Native
FedUP/FedX still returns an ascending sequence for our descending test and rejects
the aggregate test. These limitations are retained, not patched.

The attempted `FedUP + Jena outer-algebra` extension would add semantic capability.
It is withdrawn from repository execution paths and cannot enter evaluation. Its
six failed development requests and two build artifacts are retained outside the
repository for audit; the later registry-fixed build was never executed. The
quarantine receipt is
`/Users/anthonyche/xgap-data/fedup-composition-quarantine-20260912/receipt.json`.

Next engineering focuses on XGAP's real-data input path and independent evaluation
contracts. It does not turn into repairing an external baseline project.
