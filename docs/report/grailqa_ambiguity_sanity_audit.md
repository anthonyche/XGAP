# GrailQA Ambiguity Sanity Audit

## Scope

This pre-run audit examines the M13-C quantity `A(u)` without using model
outputs or performance. M13-C constructs `A(u)` from one evaluation-only
reference interpretation plus deterministic single-slot direct parent/child
substitutions in the normalized ontology. It caps each slot at eight
alternatives and retains candidates satisfying the unchanged `c_sem` bound.

At `epsilon_amb=0.10`, M13-C reported mean `A=7.712`, median `A=7`, and maximum
`A=25`. The values at epsilon 0.10 and 0.25 are identical because the bounded
direct-neighbor generator has no additional alternatives in that interval.

## Finding

`A(u)` measures the size of a mechanically bounded ontology neighborhood around
one gold interpretation. It does not establish that each neighbor is a
query-conditioned plausible reading, and it does not measure alternatives
produced from the natural-language question. The cap and ontology degree can
therefore dominate the value. Calling it query ambiguity would overstate what
the artifact demonstrates.

## Recommendation

**C. Exclude `A(u)` from the current pilot analysis.**

The frozen `Q(u)` strata remain available because they describe deterministic
pipeline complexity. `A(u)` remains in the evaluation bundle for provenance,
but M13-D does not report ambiguity performance, stratify the server run by
`A(u)`, or tune any parameter from it. A future study may define and validate a
question-conditioned ambiguity measure separately.

