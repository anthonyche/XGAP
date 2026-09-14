# Bounded relationship retrieval — optional one-shot profile v1

2026-09-14. Implements the user's approved approximate performance mode. This
is a retrieval policy over existing semantic operators, not a new algebra
operator. Old frozen profiles and policy serialization keep complete reads.

RQ: Does reducing relationship transfer and downstream inputs create a useful
answer-quality / total-online-cost tradeoff? X: the declared per-fragment row
budget B versus complete retrieval. Y: source response bytes/rows, coordinator
input work, total online latency, full-reference answer EM/F1 and numeric error.
Development uses independent tiny facts; there is no speedup acceptance claim
from a single tiny timing or a budgeted answer being returned successfully.

## Contract and algorithm

An explicit performance policy may set `retrieval_rows_per_relation=B`, with
integer 1<=B<=1,000,000. Precision rejects this option. An explicit request
`require_complete_results=true` rejects a conflicting policy before model or
backend calls. Null/absent B preserves previous source reads and identities.

For each already constructed legal physical candidate:

1. Reject semantic Traverse. This first profile supports expanded Match-based
   path programs; native shortest/path selectors require separate semantics.
2. For each native `semantic_edge_match_v1` fragment, append outer LIMIT B+1,
   then pin its template and budget. Bind VALUES are inserted before dispatch;
   the limit applies to the bound query. Entity identity/property reads remain
   complete. There is no new call, probe, candidate or post-answer row cutoff.
3. The frozen estimator keeps its original native scan/column proxies and
   weights. It caps estimated returned bytes at B+1 rows and relationship input
   work at B rows. This feature extension is explicitly uncalibrated; it does
   not assert a native internal scan bound or a latency guarantee.
4. Select one candidate by the existing frozen estimates and execute it once.
5. Capture each full native response once. If more than B+1 rows arrive, return
   a typed failure, not an approximate success. Keep the first B rows for the
   coordinator. Row B+1 is an omission sentinel, never an extra request.
6. Evaluate the original operators on these budgeted leaf relations. Preserve
   the final rows and attach observed coverage through the core trace, compact
   outcome, method receipt and answer artifact. Score against unchanged gold.

The prefix follows backend return order. It is not a uniform or reproducible
random sample. Saved-response replay reproduces the exact historical prefix;
a new live execution need not choose the same rows. No random-sampling accuracy
formula, extrapolation, unbiased estimator or confidence interval is asserted.

## Meaning, precision and bounds

Hard predicates and the requested operator/output structure are preserved, but
they are evaluated over the observed relations. Positive witness queries can
lose answers. For a direct positive relational program without aggregate-based
filtering, ranking or non-monotone conditions, retained answers have real source
witnesses. This subset statement is not extended to arbitrary programs.

COUNT/SUM/AVG/etc. are exact on the observed relations, **not** estimates proved
correct on the full source. Aggregation-based filters and rankings may change
membership and values. For example eight edge facts with B=2 yield observed
COUNT=2; the full-source gold remains COUNT=8 and answer EM=0. The output says
`budgeted_source_relations`, `aggregate_values_full_source_exact=false`, and
`ranking_full_source_exact=false` whenever omission is observed or completeness
is unknown. There is no renaming incorrect full-reference answers as exact.

If every bounded fragment observes at most B rows, no source rows were omitted
by this mechanism and the selected interpretation is complete. This remains
conditional on a consistent source snapshot and the ordinary correct lowering;
it is not proof that the model selected the user's intended interpretation.
Precision's full reads retain this complete-query execution property; stronger
NL/grounding accuracy needs its own evidence and subsequent implementation.

For R relationship fragments, wire rows <=R(B+1) and admitted relationship rows
<=RB, assuming the engines honor LIMIT. Entity reads and row byte width are
excluded; global response-byte budgets still apply. Joins can multiply those
rows. This is not a total execution-memory or polynomial query-execution bound.
Backend scans/sorts may remain large, especially with DISTINCT.

The transformation costs O(V+E+Q) time and space per candidate, where Q is total
compiled query text. It adds no domain combinations. Existing bounded polynomial
construction/selection remains unchanged. Row normalization adds O(RB) returned
rows with their encoded widths. Worst-case full-source recall can be zero;
numeric error is unbounded without data assumptions. No speed ratio is promised.

## Strategy consistency and accounting

Binding before LIMIT can select a different prefix from an unbound LIMIT. Each
budgeted candidate therefore gets a distinct equivalence key; it is not labeled
answer-equivalent to other budgeted/full candidates. Selection minimizes the
estimated cost in this policy domain, not a proved common-coverage objective.
Plan metadata records this strategy-dependent coverage. A calibrated coverage
estimator is not implemented by this change.

Original one-time source statistics/model preparation stays offline and frozen.
Query compilation, prediction, native execution, sentinel processing, response
capture and answer sealing are online work. Baselines and original evaluation
records are untouched. New evaluation must freeze B/profile and record its new
epoch before execution; no tuning B on already observed evaluation answers.

## Acceptance

Targeted tests cover actual SPARQL LIMIT, independent positive/COUNT answers,
sentinel completeness, unchanged entity reads, real bind rewriting, immutable
weights and undiscounted scan proxies, tamper/overfetch failure, one final plan,
explicit complete-result rejection and propagation of approximation markers.
A single new mixed Neo4j/Fuseki tiny gate checks native syntax, actual rows and
saved-response replay. Neither large-data speedup nor precision-quality uplift
is claimed by these engineering gates.
