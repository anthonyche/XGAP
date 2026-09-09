# GrailQA semantic validity and logical capability boundary

## Milestone and scope

D193 separates a typed interpretation contract from the legacy M5 lowerer's
implemented capabilities. It follows D192 canonical grounding; it does not
replace the original EQ1–EQ5 obligations with validity-only experiments.

The opt-in policy is `grailqa_canonical_semantic_grounding_v2`, in the separately
frozen development spec
`experiments/specs/grailqa_semantic_preflight_semantic_capability_v1_cwru_qwen3_32b.json`.
Its freeze hash is
`1876969bcf4325c4b3617c878fa999c130e8af4957940fc2c92ed5a26fa21c86`.
Compared with canonical-grounding-v1, only experiment/run identity, the explicit
policy, and the freeze hash differ. No historical spec, prompt, model, catalog,
retrieval, question order, token/repair limit, timeout or epsilon is changed.

Allowed changes are the additive typed-validation/assessment APIs, the guarded
GrailQA opt-in lifecycle, tests, and documentation. Forbidden changes include
new algebra operators, erasing IN directions, fake empty results, relaxed hard
constraints, retries, current frozen run mutations, automatic GPU resubmission,
or widening the 18-query development population.

## Implemented contracts

- `xgap.pattern.semantic_validation.type_check_semantic_path_pattern` validates
  the typed path intent independently of lowering. It retains existing
  variable/selector/restrictor rules and adds a closed recursive condition
  check, strict integer bounds, finite constants, and all node/edge reference
  bounds. Numeric references require a fixed-length path; `first`/`last` node
  references remain valid on variable-length paths. This is an explicit bounded
  contract, not a new general GPC parser or proof of answer correctness.
- `xgap.llm.candidate_assessment.assess_candidate` returns separate semantic
  validation and logical-lowering records. All missing IN/undirected,
  optional-regex and bounded-regex capabilities are reported with AST locations.
  Invalid typed candidates are `not_assessed`; known limitations are
  `unavailable`; unexpected implementation failures are `error`. Only an actual
  successful legacy lower/validate pass yields logical `available`.
- A logical plan is **not backend execution admission**. Every assessment says
  `backend_execution_verified=false`. No compiler/plugin, backend, model,
  observation, ontology service, or evaluation reference is invoked by the
  assessment. No alternative-direction approximation is generated.
- The new guarded policy retains D192's strict canonical/identity grounding
  and candidate-local isolation. It scores only semantically valid, grounded
  candidates. A valid but unsupported interpretation remains visible with its
  capability record rather than being mislabeled a type error. The existing
  `semantic_admissible` field still refers to ontology deviation, not execution.
- New states/manifests/status/metrics are versioned and policy-bound.
  `candidate_capabilities.jsonl` preserves every assessed candidate, including
  rejected candidates; metrics report logical-lowering status counts over
  validated-grounded candidates and an all-query availability denominator.
  Backend execution remains false. Old entrypoints and the D192 policy retain
  their existing behavior and old evidence is not reclassified in place.

## Source-backed diagnostic, not a new experiment

Read-only replay of the uploaded `3796877` query states verifies all 18 exact
request/prompt-view identities. The raw file SHA-256 remains
`f207a5d4e3563e391274ebc0109ce2906a5ea2a007b27f4b362823c1bd887c18`.
The 49 raw candidates comprise seven unassessed candidates in three rejected
shared envelopes, 38 candidate-local grounding rejections, and four grounded
candidates across two questions. All four pass the new typed contract. Three
have an available M5 logical plan; the fourth is explicitly unavailable because
of an IN edge at `expr.right.left.edge` (query `2102933007000`, candidate `c3`).

No model/backend call, reference-content read, semantic-score recomputation or
answer-accuracy evaluation occurred during this diagnostic. Four typed/grounded
candidates do not mean four correct answers, a coverage improvement, a repaired
RAG pipeline, or an admitted paper result. See the separately recorded
`experiments/artifacts/grailqa_guarded_3796877_capability_diagnostic_20260909.json`.

## Acceptance and remaining gates

Focused acceptance passes 204 candidate/grounding/inference/lifecycle tests and
56 shell-handoff/historical-contract tests. Full offline regression passes
**2318 tests, 36 skipped, in 598.46 seconds**. The LLM-boundary, semantic-audit,
and M15 selective-resolution offline examples pass; guarded-entrypoint help,
CPU handoff shell syntax, and `git diff --check` also pass. Skipped/live behavior
remains unverified; no live result is inferred from these checks.

The user reported CPU catalog comparison **3796968** at exact **e39b98e** as
FAILED (`1:0`, 3m18s). Its supplied traceback shows the selected
`$HOME/venvs/xgap-core/bin/python` lacks PyArrow, the project's declared
`parquet` extra (`pyarrow>=15`). The earlier record-class identity failure was
passed; Parquet iteration then failed at dependency import, not candidate
retrieval or eligibility evaluation. This is not an observed coverage result.
Preserve the failed run and baseline. Before a new manually submitted CPU job,
install/verify that dependency with the exact selected interpreter; do not
implicitly switch interpreters, overwrite the old run, or retry automatically.
No additional CWRU job has been submitted by the agent.

Still open: the CPU source-backed coverage result; schema/alias/retrieval and
prompt-visibility coverage; new provider-output quality; actual IN/undirected
execution support and its independent exact-answer tests; backend capability
admission for GrailQA physical comparisons; independent audit of any future
new-policy GPU run; both datasets' remaining semantic/physical/baseline EQ1–EQ5
cells. No full150 authority or paper admission is created here.
