# GrailQA Semantic-Deviation Postmortem

## Frozen Observation

The M13-D server summary reported identical Feasible Coverage (0.48) for every
epsilon in `{0, 0.1, 0.25, 0.5, 0.75, 1}` and no first-stage semantic-bound
rejections. That is a warning that the epsilon sweep did not exercise a useful
score range; it is not a reason to change the frozen `c_sem` formula.

## Code Audit

The query-side anchors and candidate realizations are selected in the same
structured model response. `DirectionalOntologyDeviation` then compares each
selected query anchor with the candidate realization for that slot. Exact
self-alignment is therefore possible and receives zero deviation. The
ontology-distance implementation itself still supports exact,
specialization, generalization, sibling, unrelated, and infinite outcomes.

M13-E1 adds distribution tooling for finite/infinite count, minimum, mean,
median, p90, maximum, histogram, threshold fractions, and per-query distinct
values. It does not alter any penalty, aggregation, epsilon, or M11 boundary.

## Evidence Limit

The local workspace does not contain the server's `semantic_scores.jsonl`, so
the requested candidate-level distribution cannot be reconstructed from the
aggregate summary. Run:

```bash
PYTHONPATH=src python -m xgap.experiments.interpretation_contract c-sem \
  --source-run /path/to/frozen/m13d-run
```

Conclusion: **C, insufficient evidence because retrieval/generation makes the
scores uninterpretable**. The same-prediction anchor design is an
operational-degeneracy risk to audit after the frozen rows are copied back,
but M13-E1 does not modify `c_sem`.

