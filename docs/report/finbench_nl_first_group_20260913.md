# First formal ordinary-NL group — 2026-09-13

One frozen evaluation question, `FBNS-2-a0baa0e6711f9de3`, was attempted once by
each scheduled method. All four model responses were identical compact queries
and failed structural lowering. There were four model calls, zero final method
queries and zero source requests. Every end-to-end answer score is zero, even
though the independent reference is empty: no answer is not a correct empty
answer. This is one question, not four independent accuracy observations.

| Method | Input/output tokens | Interpretation ms | Online through retirement ms | Final queries | Answer EM |
| --- | ---: | ---: | ---: | ---: | ---: |
| XGAP precision | 2629 / 541 | 3063.910 | 8404.823 | 0 | 0 |
| XGAP performance | 2625 / 541 | 3026.347 | 8846.322 | 0 | 0 |
| Shared NL + FedUP | 2629 / 541 | 3081.428 | 9185.823 | 0 | 0 |
| Shared NL + FedX | 2629 / 541 | 2945.936 | 8669.422 | 0 | 0 |

The generated `deduplicate_by=[dst,p,med]` includes path variable `p`. The frozen
prompt explicitly limits these keys to node/edge variables and exposes only path
length. The validator enforces that contract and reports `Deduplication requires
distinct node/edge variables`. The subsequent generic program-admission error
is less informative; the original lowering error and unmodified model response
are preserved in provenance. No implementation-contract mismatch was found for
this rejection. Other generated constraints have not been repaired or executed.

This is a common interpretation-front-end failure, not evidence of a FedUP or
FedX native semantic/execution failure. It does not support a comparison of
planners or execution speeds. The earlier fixed-semantics results isolate the
backbone; this result demonstrates why NL effectiveness must be reported
separately. No inference about overall accuracy follows from this first group.

All four sessions drained their owned groups, stopped observers and discarded
only reconstructable serving copies. The controller exited zero. Model calls,
failed intents, token usage, costs, independent scores and response bytes remain
archived. Startup costs are separate; the table includes required post-outcome
retirement, as in the fixed-semantics report.

Evidence: [machine-readable rows](../../experiments/artifacts/finbench_nl_first_group_20260913.json),
[CSV](../../experiments/artifacts/finbench_nl_first_group_20260913.csv), and the
hash-pinned audit referenced by those files. No new model/query calls were made
for the audit. Do not rerun this question, tune its prompt or remove it from the
frozen 48-question denominator. Continue unrun groups under their original
protocol; native store preparation is the next engineering boundary.
