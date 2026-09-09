# Inline grounding: executable candidate interface simplification

## Goal and scope

D197 / H3 removes duplicated grounding serialization from model output while
preserving semantic choices and the existing guarded inference/evaluation path.
The permitted changes are an additive wire-format materializer, explicit
provider/model selection, original/derived evidence linkage, replay support,
one new model bundle/development spec, tests and documentation. Frozen earlier
bundles/specs/results, retrieval, semantic scoring, reference equality, algebra,
budgets and native execution are unchanged. No server or model is invoked by
the local acceptance checks.

The hypothesis is that asking for slot choices at their actual AST components
reduces avoidable serialization errors. Model effectiveness and real request
token counts are **unmeasured**. Software acceptance establishes integration
and semantic preservation, not improvement on the 18 development questions.

## Wire format and deterministic assembly

The selected contract is `inline_grounding_v1`, with the explicit entity
identity property `type.object.id`. A candidate still supplies the full typed
`pattern_query`. `label_slot` attaches a slot selection to the existing node
or edge label; `property_slots` associates property slots with literal property
keys; `condition_slot` identifies a condition's single common property key.
The model no longer repeats `grounding.slot_realizations`, structural
`component_ref` paths, copied ontology-term IDs, or a separate entity-ID list.

The materializer traverses the actual tree and produces those references and
the identity literals already present. It preserves Seq/Alt association,
unary expressions, directions, source/target choice, selector/restrictor and
the entire condition. Flattening paths was deliberately avoided because the
frozen interpretation comparator still includes the expression-tree shape.
This change does not silently redefine that comparator's equivalence classes.

Top-level query anchors remain explicit model choices, including anchors for
candidate-optional slots. Missing slots or labels are not inferred. Duplicate
slot declarations, invalid identity literals, nonexistent property components
and ambiguous condition annotations reach the existing per-candidate canonical
grounder as invalid declarations; no arbitrary term is chosen. Thus a bad
semantic sibling does not discard a good one. Malformed wire/AST structures
still fail the existing shared response boundary. Expression/condition
materialization has an explicit 64-level structural nesting bound.

The existing typed semantic validator and canonical prompt grounding remain
mandatory in the selected development spec. Unsupported lowering is still a
separate capability result. The historical query-anchor self-alignment concern
for `c_sem` is not solved by serialization changes and remains in the design
review; no epsilon/accuracy claim is made here.

## Runtime and evidence

The normal ModelBundle provider factory reads the explicit, hashed response
contract from model metadata and verifies agreement with its wire schema.
Unknown or mismatched contracts fail rather than selecting a fallback. Models
without this metadata keep their previous behavior and hashes. The guarded
environment checker also compares the effective response contract to the
selected model bundle before inference.

The ordinary provider parses and validates the materialized response, then
uses the existing token-guarded provider, canonical grounding, typed feedback
and semantic inference/evaluation path. No second repair loop is introduced:
malformed JSON, wire format, grounding and typed errors share at most one repair.
At least one valid candidate prevents a quality retry; transport failures never
request repair. Every actual repair retains the original wire response and is
checked against the existing full-request token limits before transmission.

`LiveInvocationArtifact.structured_response` remains the actual model wire
response. Additive `response_materializations` records source-response,
request and transmitted-payload identities, the generated response, its hash
and the call index. Inference consumes the generated response. Feedback states
that its input is the materialized representation and links its source hash
to that record. Neither original raw responses nor earlier repair evidence
are overwritten. The provider rejects a validator that mutates a materialized
response after it has been hashed; this is an internal failure, not another
model repair opportunity.

Read-only replay recomputes a successful final materialization from preserved
model content and checks its call, source and payload links. Rehashing a
tampered derived body cannot make it valid. Replay remains a deterministic
parsing/grounding diagnostic; it is not full new-protocol admission, server
identity attestation, semantic accuracy, or a paper result.

## Selected artifacts and acceptance gate

- Model bundle: `models/qwen3_32b_vllm_cwru_grailqa_inline_v1/`.
- Development spec:
  `experiments/specs/grailqa_semantic_preflight_inline_grounding_v1_cwru_qwen3_32b.json`.
- The only differences from the D194 development spec are the experiment/run
  identity and selected model-bundle path/hash. The same 18 questions/order,
  catalog, retrieval, epsilon values, model family, sampling, 8192 input /
  4096 output budgets, timeout, at-most-two attempts, tokenizer probes and
  no-backend scope are retained. Old launch defaults remain old defaults.
- The new system prompt and schema are separately versioned with no examples.
  Actual request comparison changes only the system prompt and wire schema;
  the inference question, visible context, grounding contracts and other
  serving parameters are unchanged.
- Targeted acceptance covers AST preservation, original/derived records,
  mixed valid/invalid siblings, shared repair bounds, repair token refusal,
  timeout, actual guarded inference and evaluator integration, schema
  validity, replay corruption detection and unchanged old identities.

The first full regression exposed one historical-review check comparing the
original provider hash to later source. Its test now reads that source from
the review's declared base commit, as it already did for two earlier changed
modules. The historical review and its hashes remain untouched. The expanded
focused regression passes 297 tests in 2.28 seconds. The fresh full suite after
this harness correction passes **2546 tests, with 37 explicit skips, in 608.62
seconds**. The harness check and all 19 acceptance examples pass with the same
production source. No production code changed after either full-suite start.

The durable result and source hashes are in
`experiments/artifacts/d197_inline_grounding_local_20260909.json`, with current
next actions in `docs/engineering_state.md`. Real Qwen/vLLM
schema acceptance, request fit and effectiveness require a fresh bounded
development run and a restored CWRU session. The pending CPU catalog result
must first determine which catalog is selected. A new catalog and new output
format should not be conflated as one causal improvement. No full150 run,
scientific population change, backend measurement or study completion follows
from this interface implementation.
