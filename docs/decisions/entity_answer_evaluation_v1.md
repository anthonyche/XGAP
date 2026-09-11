# E1-B: independent entity-answer evaluation

Frozen on parent72aeea7, 2026-09-11. R-E/E1 requires answer EM/F1 and a failure
funnel, distinct from structured validity and execution success. The new
experiment-only evaluator consumes completed E1-A records and evaluation-only
normalized GrailQA references. It performs no generation, selection or execution.
Callers must seal inference/execution before opening references; a pure evaluator
cannot prove the caller obeyed temporal isolation. Existing frozen150 is unchanged.

The original explicit question population determines order and every denominator.
References must cover it exactly; execution records may be incomplete, with every
missing question visible as not_run. Missing execution is not an empty answer and
has unknown cost. Terminal failures have EM/F1 zero even when gold is empty;
successful empty/empty has EM/F1 one. Macro quality is published only when all
questions have terminal records and all references fit entity identity semantics.
Unsupported scalar references remain visible and prevent a full-cohort score.

Expected entity IDs map to the declared Freebase namespace; labels never score.
Actual answers use the existing strict RDF AnswerProjection/exact_answer_match.
Entity-set F1 uses 2*|intersection|/(|actual|+|expected|), empty/empty one. Duplicate
entities do not add weight. Scalar value equivalence and official whole-benchmark
scoring are outside this profile. Never rename a source-partial check as GrailQA
accuracy. Cost sums retain failed attempts and explicit unknowns, without imputing
zero or subtracting one method's timings from another. Method/policy/epsilon and
record schema mismatches fail rather than mixing experiment cells.

Allowed: new evaluator, focused tests, evidence/report/status records, and durable
recovery of the already existing query-independent D201 fact cache. Forbidden:
changing gold/populations/inference/P1/runtime, starting a service/model, rebuilding
catalog/facts, rerunning accepted gates or operating job3804210. Acceptance: one
new controlled E1-A→independent-scoring vertical slice plus mixed-success/failure,
empty/unrun/unsupported, identity and cost counterexamples. Preserved source cache
is checked against existing hashes, not regenerated. This gate is not a new model
or native benchmark measurement.
