# E1-A: model-owned entity projection with existing grounded candidates

Frozen scope at parent22c20e3 on 2026-09-11. R-E/E1 needs answer meaning from
inference, followed by the ordinary deterministic executor. Preserve the existing
query anchors, grounded candidate pool and directional ontology deviation; do
not replace this experiment with the separate single-program toy interpreter.

Create a separate `xgap-grounded-entity-answer-v1` wire/model bundle. Each
candidate retains the existing explicit grounding envelope and adds mandatory
`predicted_projection={kind:path_node, position:first|last|1..4}`. No default,
variable-name inference, answer lookup or reference position is allowed. The
closed inline-grounding format and frozen150 semantic-only protocol stay intact.
The parser validates the complete new JSON Schema (including nested fields),
then reuses the normalized path parser. The `entity-answers` optional dependency
pins jsonschema4.26.0; missing dependency or schema mismatch fails before a model
call. Unknown fields must not silently disappear during normalization.
Existing canonical grounding and ontology deviation run unchanged. Preserve raw
responses, candidate IDs, failures and the prediction in a full-meaning hash.

Before generation, explicit required entity IDs must be visible. For an anchored
question with no confirmed IDs, a unique catalog entity supplies the one allowed
identity; multiple visible identities require clarification, and zero requires
grounding. The selected query must enforce all required IDs with positive
identity conditions. The input question, request and program remain gold-blind.

Freeze two selection policies: semantic_bound uses grounded, type-valid candidates
with finite c_sem<=epsilon, ordered by c_sem, descending confidence, full-meaning
hash and ID. model_top1 uses the same type/grounding admission and orders by
descending confidence, full-meaning hash and ID without an epsilon filter. No
backend execution availability or cost participates in meaning selection. Once
selected, an unsupported candidate fails without trying a sibling. Positions are
part of full meaning and never changed by P1. c_sem measures ontology-slot
deviation only: neither position correctness nor answer F1 is bounded by epsilon.

The selected normalized query plus its explicit projection becomes the existing
Traverse→Project semantic program and enters INT-4. There is no caller-supplied
answer position. Preserve generation and execution ledgers, unknown token usage,
all attempted calls and end-to-end time. Production provider uses existing
token-guarded journal/transport with one generation and zero repairs; admission,
between-stage deadline and finite backend budgets precede dispatch. No new
retry, model serving framework, catalog builder or large-data run is added.

Allowed files: new experiment contract/orchestrator, its optional dependency,
separate new model bundle,
new focused tiny tests and status/decision/report/evidence records. Do not modify
the queued08e4b3b package, frozen150/48 oracles/populations, shared logical/compiler/
P1 semantics, existing providers/materializers or historical evidence.
Acceptance: controlled HTTP response through the actual token guard, parser,
grounding/scoring, selection and ordinary compiled SPARQL execution on tiny RDF;
different predicted positions affect answers, unsupported selected meanings do
not fall back, and malformed/ambiguous/budget/failure cases retain evidence.
Only new risk-related checks run. No native rerun is needed for unchanged native
boundaries. Controlled transport is not model quality or a benchmark result.
