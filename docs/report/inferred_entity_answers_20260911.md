# E1-A: inferred entity answers through the existing execution chain

On parent22c20e3, the separate `xgap-grounded-entity-answer-v1` entry now connects
model-owned answer projection, existing canonical grounding/ontology scoring,
meaning selection, and INT-4's ordinary P1 execution to typed entity answers.
This closes a concrete R-E/E1 wiring gap; real model quality remains unmeasured.

Each candidate must supply `predicted_projection={kind:path_node, position:...}`.
The position is explicit first/last or one-based1..4, then checked against the
selected fixed1–3-hop path before backend work. There is no caller answer position.
Full JSON Schema validation rejects unknown nested fields before the existing
normalized parser can discard them. The optional `entity-answers` dependency pins
jsonschema4.26.0; dependency and schema checks precede model generation.

The original query slots, visible entities and directional ontology deviation
are reused. Required identities are visible and explicitly sent in the same
request used by both parsers. Ambiguous unconfirmed identities stop before model
work; selected meaning must positively enforce every required identity.

Two policies are frozen: `semantic_bound` admits grounded/type-valid candidates
with finite c_sem<=epsilon, sorting by c_sem then confidence; `model_top1` keeps
type/grounding admission and sorts by confidence without the epsilon filter.
Both break ties by full-meaning hash then candidate ID. Projection participates
in that hash. No cost, backend support or evaluation data selects meaning, and an
unsupported selected candidate fails without trying a sibling. The new selection
adds linear candidate serialization/hash work and O(m log m) sorting for m<=3;
this is not an approximation guarantee over all meanings. Existing P1 bounds
are unchanged. Epsilon bounds ontology-slot deviation, not projection or F1.

The separate model bundle uses the existing guarded production provider/journal,
one generation, zero repairs, timeout<=120s and8192/4096 token limits. Contradictory
reported call counts/completion cannot enter backend execution. Actual request,
raw generation, candidate scores, selected meaning, full agent execution, costs
and unknown usage are retained. Calls and row budgets are finite; deadline checks
occur between stages and do not cancel in-flight calls. Clients own their own
timeouts/result limits. The reused QuestionBudget.max_binding_bytes concerns
cross-source binding payloads, absent from this single-source profile; it is not
a wire-traffic or peak-memory guarantee. No evaluation file is opened here.

## Focused acceptance evidence

Only `tests/test_inferred_entity_answers.py` ran: **23 passed,0 failed,0 skipped**
on its first run in1.13s (process1.644s; tool d0d6b2 exit0). Source, test, dependency,
contract and model bundle hashes did not change across the run. Controlled HTTP
responses use the actual provider/token guard; a synthetic token counter is
explicit. Actual compiled SPARQL executes on independent tiny RDF through
FusekiClient's transport override and RDFLib. Expected answers are handwritten.

Checks cover first/last positions returning different entities and hashes,
ontology deviation0 versus1/6 producing different policy choices and answers,
projection retention/missing projection, selected unsupported meanings without
fallback, identity confirmation/positive anchors, token denial/transport failure,
backend and answer-row budgets, execution failure, unknown nested fields and
three contradictory provider-record cases. No native service, actual model,
catalog, large dataset or old successful gate ran. No failure rerun was needed.

Raw log and receipt: `/Users/anthonyche/xgap-data/e1a-inferred-entity-answers-20260911/`.
Machine evidence: `experiments/artifacts/inferred_entity_answers_20260911.json`.
Bundle hash validation is separately retained; real pinned-tokenizer preflight
for this new bundle and real generation have not run. No server package was made.

The frozen150 runner remains semantic-only; original150/48 populations, all
failures and the FinBench three integration-exposed IDs are unchanged. Remaining
E1 inputs include query-independent real facts and independent scoring; broader
E1–E5 still need real prior forecast/cost preparation and fair comparisons. Do not
substitute this local gate for GrailQA accuracy or native performance evidence.

The user now observes job3804210 PENDING(Resources), runtime0, no node assigned,
and will report changes. Its frozen08e4b3b package stays unchanged: no query,
resubmission or resource switch was requested. Original model0/5 and real
FinBench6/6 retain their different scopes and remain the actual prior results.
