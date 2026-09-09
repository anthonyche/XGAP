# GrailQA output-contract clarification — separate draft v1

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: plan (existing engineering scope; no scientific choices inferred)
- Origin Date: 2026-09-09
- Verification Status: UNVERIFIED for model effectiveness
- Version Label: grailqa_output_contract_revision_draft_v1
- Base implementation: `2379069135ee971a770429323889d17ec0f29639`

## Objective and scope

Clarify the existing response interface so a model can express a valid bounded
interpretation without guessing serialization conventions. This addresses the
recorded missing top-level anchors and invalid component references; it does
not alter the grounder, infer missing anchors, repair variable names, or claim
that a previously rejected answer becomes correct.

The old prompt already requires an anchor for every supplied slot. The draft
makes the two different cardinalities and the structural reference grammar
explicit. It adds syntax instructions, not query/answer examples. Whether it
reduces model failures is an **unmeasured engineering hypothesis**.

Allowed changes in this milestone: a new model bundle, a new preflight spec,
this review record, offline regression tests, and status/decision documents.
Forbidden: changing frozen files or raw logs, altering validation/normalization,
adding repair calls, changing retrieval or scientific choices, invoking models
or backends, submitting jobs, or minting author approval.

## Proposed interface

| Location | Existing requirement clarified by the draft |
|---|---|
| Top-level `query_slots` | Every supplied slot exactly once, including candidate-optional hops; each anchor comes from that slot's allowed IDs |
| Candidate `grounding.slot_realizations` | Required slots exactly once; optional slots at most once; unused optional hops do not force extra path structure |
| Candidate relation hops | Every actual relation leaf is assigned its corresponding hop in recursive left-before-right structural order |
| Class component reference | `source` or `target`, not a variable or `.label` field |
| Relation component reference | Start at `expr`, follow the actual `.left`/`.right`/`.child` tree, end in `.edge` |
| Property component reference | An existing endpoint/edge property entry, or `condition` when that component exists; exact property keys are retained |
| Semantic alternatives | Query anchors and candidate terms need not equal; candidate relation terms must agree with their actual relation labels |

All original instructions remain at the start of the new prompt. The existing
relation-endpoint visibility exception, all-or-nothing grounding behavior,
canonical defaults, and rejection of generated `node_not_equals` remain
unchanged. Describing unary/alternative component paths does not authorize
unsupported query semantics or extend the fixed-path profile.

## Versioned artifacts and activation boundary

- Proposed bundle: `models/qwen3_32b_vllm_cwru_grailqa_contract_v1/`
- Proposed 18-query spec:
  `experiments/specs/grailqa_semantic_preflight_output_contract_v1_cwru_qwen3_32b.json`
- Exact proposed/preserved identities:
  `experiments/artifacts/grailqa_output_contract_revision_draft_v1.json`

The schema-format version remains compatible; the bundle ID/version, prompt
hash, model-bundle hash, preflight identity, and freeze hash are new. The old
bundle/spec and paper draft v2 stay byte-for-byte intact. Existing shell
defaults still select their old artifacts. This is an opt-in review draft,
**not an execution authority**; possession of a valid spec alone is not author
approval. No new submission helper or live job is activated by this change.

The proposed small validation retains all 18 original query IDs and their order,
including the provider failure and the 13 catalog/retrieval/visibility-limited
queries. The five jointly reachable queries remain a diagnostic subset, not a
replacement population. Catalog, retrieval, prompt visibility, model, sampling,
candidate cap, epsilon, scoring, and failure reporting are unchanged.

## Offline acceptance and remaining inputs

Tests must prove exact allowed-field differences, unchanged old file bytes,
valid model/spec hash chains, unchanged context reservation arithmetic, and
that constructing the actual provider payload changes only the system prompt.
Synthetic examples must exercise the actual normalized parser and grounder:
valid one/two/three-hop references pass; missing/duplicate anchors, wrong hop
order, unknown slots, variables, label fields, and nonexistent paths fail.
Visible semantic alternatives remain allowed.

Offline acceptance on 2026-09-09: the full collected suite passed **1,309 tests
with 36 skips** (517.66 seconds). The final two new contract-test files passed
**61 tests** together, including 53 grounding cases added after full-suite
collection; those 53 are not included in the 1,309 count. Both offline boundary
examples passed. The final focused run verifies the recorded proposed and
preserved file hashes. These checks establish interface fidelity, not model
effectiveness or live request-token fit.

No model tokenizer is available in the inspected local Qwen cache. The existing
8,192-input + 4,096-output reservation equals the 12,288 served context, but this
arithmetic **does not measure the new serialized request length**. Before a
model call, a separate read-only server-side check should use the pinned cached
tokenizer and actual chat template to count every proposed generation request.
A future repair body depends on the not-yet-produced response, so its exact
input length cannot be measured in advance; it also needs a token-limit check
before transmission. An over-budget request must be reported, not silently
truncated or accommodated by changing the frozen limits.

The already audited pilot150 catalog need not be rebuilt merely because of a
system-prompt change. Existing catalog/readiness identities must still verify
for the chosen spec; this statement is not a fresh CWRU verification.

## Next gate

1. Explicitly review this interface change and the exact small validation scope.
2. Verify server-side artifact/model identities and actual token lengths without
   inference; do not rebuild or modify the old evidence tree.
3. Only after separately scoped authorization, perform one fresh development
   validation with the new identity. Retain all failures, use the existing
   bounded syntax/schema repair, and do not add grounding-driven retries.
4. Independently audit and report new results alongside the immutable original
   negative result. Do not call a before/after difference causal evidence.
5. A later paper protocol must explicitly bind the reviewed prompt and new
   preflight evidence. The existing five scientific choices, author review,
   admission, and exact 150-query authority are still required.

The proposed preflight retains at most two calls per query (one generation plus
the existing bounded repair), hence at most 36 **question-level** calls. Any
separate deployment smoke is not included in that number and must be explicitly
accounted for when preparing execution authority. This document submits nothing.

The admitted FinBench physical result is unaffected. Semantic `paper_result`
and all new execution-authority flags remain false.
