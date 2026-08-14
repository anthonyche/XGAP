# M12-B LLM Boundary End-to-End Audit

## 1. Executive conclusion

**PASS:** the required M12-B fixes are implemented and verified by a
credentialed post-fix smoke run, so M12-C may proceed.

The successful `fr-q001` run proves live-provider and deterministic-pipeline
compatibility, not natural-language interpretation accuracy. The audit found
three concrete gaps: the exact assembled request was not persisted, empty
prompt context was accepted by the provider request builder, and
`component_ref` was checked only for non-emptiness. These are fixed in the
current tree. The zero-shot prompt was also minimally expanded because the
historical output itself demonstrated semantic confusion; no few-shot examples
were added. The post-fix run is preserved at
`runs/m12b-live-qwen-smoke/` (the run tree is intentionally git-ignored).

Direct answers to Q1-Q15:

| Question | Answer |
|---|---|
| Q1 | Qwen received the question, a 4-slot bounded schema view, 9 visible ontology terms, 1 entity, 10 source-schema hints, backend mapping hints, the complete structured schema in the user message, the short system prompt, model/sampling bounds, and `response_format={"type":"json_object"}`. |
| Q2 | From `structured_schema.json`, embedded verbatim as `structured_output_schema` in the user-message JSON; DashScope did not receive it through `response_format.json_schema`. |
| Q3 | In the historical request, only from the short system prompt, field names, and ontology/schema context; field semantics were not explicitly defined. |
| Q4 | Yes. Without semantic instructions the model must infer meanings such as `seq`, `source`, direction, selector, and `component_ref` from names and prior knowledge. |
| Q5 | The model output is already controlled `PathPatternQuery` JSON. Parsing constructs the typed AST; there is no arbitrary-text-to-pattern transformation. |
| Q6 | No. Parsing, type checking, lowering, and plan validation prove legal XGAP structure, not agreement with the NL question. |
| Q7 | Deterministic retrieval defines `S(u)` and its candidate anchors; the LLM selects one shared `a_u(s)` per slot during generation. |
| Q8 | The LLM supplies each candidate's slot realization and `component_ref`; deterministic code validates visibility, coverage, component existence/kind, and mappings. |
| Q9 | It may emit an unseen string, but runtime validation rejects it as `hallucinated_ontology_id`. |
| Q10 | Missing bundle files fail loading; an empty prompt view now fails before network I/O; missing mappings produce explicit insufficiency rather than fallback. |
| Q11 | No inference-path financial-risk ontology fallback was found under `src/xgap`; the terms come from the DatasetBundle. The older smoke-result normalizer is dataset-specific but is not an ontology source. |
| Q12 | Only pipeline compatibility plus one plausible candidate, not general NL interpretation quality. |
| Q13 | Not from the historical run alone. The post-fix run now persists the exact assembled messages, embedded schema, response format, endpoint, timeout, and model parameters in `llm_requests.jsonl`. |
| Q14 | No. The historical prompt requested multiple candidates but did not define semantic distinctness. The minimal prompt fix now does. |
| Q15 | Minimally fixed and live-verified; M12-B can now be frozen at this boundary. |

## 2. Actual LLM input

For the audited run, `OpenAICompatibleStructuredCandidateProvider` was built
from the live ModelBundle in `live_run._provider`. For each supported question,
`run_live_experiment` built a `PromptSchemaView`, then a `PlannerRequest`, and
called `generate_candidates`. `build_request_payload` assembled this request:

```text
POST https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
model: qwen3-max-2026-01-23
temperature: 0.0
top_p: 1.0
max_tokens: 4096
seed: absent (unsupported)
provider-specific extras: none
response_format: {"type": "json_object"}
timeout: 120 seconds
```

The first message was the exact historical system message stored in the run:

```text
You produce bounded XGAP semantic interpretations. Choose one query-side ontology anchor for every supplied query slot, then return at most M PathPatternQuery candidates. Ground every candidate slot with only prompt-visible ontology/entity/relation IDs and identify the realizing pattern component. Follow the JSON schema exactly. Never emit Cypher, SPARQL, GQL, native_query, query_text, backend assignments, costs, or physical plans.
```

The second message was `json.dumps(user_payload, sort_keys=True,
ensure_ascii=True)`. Its exact top-level fields were:

```json
{
  "task_id": "m12-financial-risk-qwen-live-dev-task-1",
  "question": "Find recipient accounts reached from Alice through ownership and transfer edges.",
  "max_candidates": 3,
  "schema_hints": [
    "edges.labels:OWNS",
    "edges.labels:TRANSFER",
    "nodes.labels:Account",
    "nodes.labels:Person",
    "rdf.classes:Account",
    "rdf.classes:Person",
    "rdf.classes:Transfer",
    "rdf.predicates:fromAccount",
    "rdf.predicates:owns",
    "rdf.predicates:toAccount"
  ],
  "prompt_schema_view": "the complete persisted bounded view",
  "structured_output_schema": "the complete structured_schema.json object",
  "requirements": {
    "choose_query_anchors_from_visible_candidate_ids": true,
    "ground_every_candidate_slot": true,
    "native_query_text_forbidden": true
  }
}
```

The reconstructed historical payload hash is
`57f9b722a510ea61eacd13cf83414c360e3e710339db0cf6870f021e9b2ff6f0`;
the canonical user-message object hash is
`4e960c74481d34eb5366154e767eaec940606c577c02f5528344700dcef7fa9a`.
The reconstructed view equals the persisted view, and the prompt/model/schema
hashes agree with the run. Thus Qwen received much more than `prompt.json`.

DashScope's mode is important: the API-level `response_format` requested only
a JSON object. The XGAP JSON Schema was conveyed inside the user message. The
vLLM template instead uses the API-level `json_schema` response format.

## 3. Actual LLM output

`raw_model_responses.jsonl` records one provider envelope and one parsed
structured object. It contained no prose outside the JSON contract and no
native query, backend assignment, cost, or physical plan.

| Candidate | Parsed pattern | Semantic audit |
|---|---|---|
| `candidate-1` | `Person(entity_id=person-alice) -OWNS-> -TRANSFER-> Account`, `ALL`, `WALK`, depth 2 | A genuine and plausible interpretation. All four slot realizations point to the expected source, edge, edge, and target components. |
| `candidate-2` | Same two-edge path with target `FinancialEntity` | A genuine broader target interpretation. Its rationale incorrectly says "intermediate" although the changed component is the target. It is structurally and grounding-valid. |
| `candidate-3` | The same `PathPatternQuery` as candidate 1, with the account slot realized as `PersonalAccount` | Invalid grounding: the class realization points to `expr.left.edge`. Its rationale also claims an intermediate node type that the pattern does not represent. Historical validation accepted it because `component_ref` was only checked for non-emptiness. |

The response's inner `provider_id="xgap"` and `model=<task-id>` are not the
actual provider identity; the outer invocation artifact correctly records
DashScope and `qwen3-max-2026-01-23`. These inner fields are informational and
unused downstream.

## 4. PathPatternQuery schema audit

The schema exposes the actual M10 candidate envelope and most of the complete
`PathPatternQuery` shape:

- required candidate ID, confidence, rationale, pattern, and grounding;
- source/target node patterns with variable, label, and properties;
- edge patterns with variable, label, properties, and `OUT|IN|UNDIRECTED`;
- recursive regex tags `rel`, `seq`, `alt`, `plus`, `star`, `optional`, and
  `bounded`, including repetition bounds;
- selector enums `ALL`, `ANY`, `ANY_K`, `ANY_SHORTEST`, `ALL_SHORTEST`,
  `SHORTEST_K`, and `SHORTEST_K_GROUP`, plus optional `k`;
- path restrictors `WALK`, `TRAIL`, `ACYCLIC`, `SIMPLE`, and `SHORTEST`;
- path variable, condition, and optional maximum depth;
- shared query-slot anchor selections and per-candidate ontology term,
  component reference, and entity grounding;
- `additionalProperties: false` at the root, candidate, pattern, node, edge,
  selector, grounding, and slot-record boundaries.

Unknown native-query fields are therefore schema-invalid at those boundaries,
and the M10 parser independently rejects `native_query`, `cypher`, `sparql`,
`gql`, and `query_text`.

The schema communicates syntax, required fields, and enums, not operational
meaning. Two limitations are explicit: `condition` is only `object|null`
rather than a recursive schema for the parser's scalar-condition tags, and
dynamic ontology IDs/component references are plain strings because their
allowed values come from the per-question view. The candidate cap is enforced
by the request and parser, not `maxItems` in the static schema.

## 5. PathPatternQuery semantic-instruction audit

The historical context is **B: structurally sufficient but semantically
underspecified**. It says "semantic interpretations" and forbids downstream
work, but does not define first/last node semantics, path composition, edge
direction, regular-path operators, selectors/restrictors, scalar conditions,
component-reference syntax, or the difference between distinct semantic
readings and formatting variants.

The model therefore learned structure from JSON Schema and vocabulary from the
bounded view, while inferring semantics from English field names and its prior
training. Candidate 1 shows that this can work; candidate 3 shows that it is
not a sufficient contract. Deterministic fake-provider control also confirms
that replacing the ownership edge label with `TRANSFER` can still parse,
type-check, lower, validate, and pass ID/kind grounding checks. That output is
legal XGAP syntax but wrong for the question.

The minimal fix keeps zero-shot generation and adds concise semantics for
source/target, regex composition, direction, labels/properties, selector,
restrictor, depth, typed component references, and semantically distinct
candidates. Few-shot examples remain empty. This is contract clarification,
not prompt optimization.

Confidence and rationale are parsed and persisted as metadata. M11 orders by
candidate ID and its deterministic objective; neither field changes `c_sem`,
cost estimation, BnB, or top-K selection.

## 6. Bounded ontology/schema context

For `fr-q001`, the model saw nine ontology terms:

```text
classes: Account, CorporateAccount, FinancialEntity, Person, PersonalAccount
relations: FinancialRelation, Ownership, RecentTransfer, Transfer
```

It saw aliases `owns`, `recent transfer`, `sent money to`, and `wire transfer`;
domain/range for Ownership and Transfer; one entity candidate
`person-alice`/Alice of type Person; ten source-schema hints; and
reference-evaluator representations for every visible term. It saw no
property term for this question, although the `RecentTransfer` backend hint
mentions `occurred_on`.

The four pre-generation slots were:

| Slot | Mention/kind | Candidate anchors |
|---|---|---|
| `slot-1-person` | Alice/class | Person, FinancialEntity |
| `slot-2-ownership` | ownership/relation | Ownership, FinancialRelation |
| `slot-3-transfer` | transfer/relation | Transfer, FinancialRelation, RecentTransfer |
| `slot-4-account` | account/class | Account, CorporateAccount, FinancialEntity, PersonalAccount |

`OntologyContextRetriever` uses deterministic normalized lexical/alias and
entity-type matching, ontology neighbors, fixed tie-breaking, and limits of 8
slots, 4 candidates per slot, 4 entities, and 12 schema items. The actual view
contains 4/4/1/10 respectively. It does not expose the full 18-term ontology.

`PromptSchemaViewBuilder` obtains backend hints and source items only after
retrieval has bounded the visible terms. Gold answers, gold logical forms,
gold alignments, and evaluation labels are absent from the view and runtime
question record.

## 7. Query anchor and slot realization audit

The implementation represents the Chapter 3 quantities as follows:

```text
S(u)                    PromptSchemaView.query_slots
candidate set for s     PromptQuerySlot.candidate_anchor_ids
a_u(s)                  top-level QueryAnchorSelection.query_anchor_id
rho_I(s)                CandidateSlotRealization.component_ref
tau(rho_I(s))           CandidateSlotRealization.ontology_term_id
I = (P, tau)            PlannerCandidate.pattern_query + its slot realizations
```

`S(u)` and each bounded candidate set are deterministic retrieval output. The
LLM selects one `a_u(s)` during the same generation call, before the response
is split into candidates. The selected anchors are top-level and shared, so
individual candidates cannot silently redefine the query-side reference.
The LLM separately chooses each candidate's `rho_I(s)` and ontology term.

Before this audit, validation guaranteed one visible query anchor per slot,
one visible realization term per candidate slot, exact slot coverage, visible
entity IDs, and backend mapping sufficiency. It did not establish that
`component_ref` existed. The current fix enumerates real source, target,
recursive edge, property, and condition component references and requires the
slot, ontology term, and component kinds to agree. It would reject historical
candidate 3 as `invalid_candidate`.

This validates grounding identity and typed attachment, not NL correctness or
full correspondence between a logical label and the model's ontology claim.
Those remain Level 4 evidence questions.

## 8. End-to-end successful candidate trace

For `fr-q001/candidate-1`:

1. `DatasetQuestion.text` supplies the NL question; the run artifact is
   `questions.jsonl`.
2. `OntologyContextRetriever.retrieve` and `PromptSchemaViewBuilder.build`
   create the bounded view in `prompt_schema_view.jsonl`.
3. `OpenAICompatibleStructuredCandidateProvider.build_request_payload` and
   `generate_candidates` send the two-message request. The historical run has
   no assembled-request artifact; future runs write `llm_requests.jsonl`.
4. DashScope returns the envelope in `raw_model_responses.jsonl`.
5. `parse_planner_response` and `parse_path_pattern_query` construct the M10
   `PlannerCandidate` and typed `PathPatternQuery` recorded in
   `candidates.jsonl`.
6. `validate_candidate` calls `type_check_path_pattern`,
   `lower_path_pattern`, and `validate_plan`. The resulting deterministic plan
   is the candidate-1 logical-plan artifact.
7. `parse_grounded_planner_response` validates the shared query anchors and
   candidate realization. `FileBackedRuntimeAlignmentProvider.resolve`
   creates `OntologyAlignmentContext`; evidence is in `grounding.jsonl` and
   `alignment_results.jsonl`.
8. `DirectionalOntologySemanticDeviationScorer.score` compares the four
   shared query anchors with candidate 1's four exact terms. Its `c_sem` is
   `0.0`, recorded in `validation.jsonl` and the physical artifact.
9. `XGAPPhysicalPlanner.plan` deterministically lowers again, indexes the
   logical plan, runs bounded BnB, and obtains one complete reference-evaluator
   representative. The trace has 10 events and a complete incumbent with cost
   upper bound `6.075212580923305`.
10. Candidate 1 is top-K selected with Nash score `17.94359056430752`.
    `ExistingCompilerAdapter` emits an executable XGAP logical reference-plan
    artifact under `plans/physical/` and `queries/`; M12-B does not execute a
    live backend here.

Therefore the LLM output is interpreted directly as `I=(P,tau)`: `P` is the
typed path pattern and `tau` is the validated per-slot ontology realization.
All lowering, validation, scoring, search, and compilation after that boundary
are deterministic for fixed artifacts/configuration.

## 9. Rejected candidate trace

The historical `candidate-2` is **non-selected, not rejected**. It passed M10,
grounding, mapping, `c_sem=0.041666666666666664`, and M11 physical search. Its
search trace has 10 events, ends complete/feasible with the same cost upper
bound, and its candidate record says `eligible`. No physical file was emitted
because `top_k=2`: candidates 1 and 3 had higher Nash scores, so candidate 2
was outside the final deterministic ranking slice.

Historical candidate 3 is the true audit rejection under the corrected
contract: its class slot points at a relation edge. Replaying that raw response
through current grounding validation fails explicitly before `c_sem` and M11.
The old selected candidate-3 physical artifact is evidence of the discovered
bug, not evidence that its grounding was correct.

This distinction matters: schema-valid model output may be rejected during
grounding, may be eligible but outside top K, or may become a selected physical
plan. These states are not interchangeable.

## 10. Four levels of correctness

| Level | Deterministic guarantee | Not guaranteed |
|---|---|---|
| 1. JSON/structured output | JSON object extraction, M10 envelope parsing, candidate cap, forbidden native fields, required grounded shape, optional one-time repair. | DashScope's `json_object` mode does not itself enforce the supplied JSON Schema; XGAP parser checks are authoritative. |
| 2. PathPatternQuery structure | Typed AST construction, type check, deterministic lowering, logical-plan validation, explicit unsupported constructs. | Whether the legal pattern means what the question asks. |
| 3. Ontology grounding | Visible IDs, exact slot coverage, shared query anchors, visible entities, ontology membership through the view, typed valid component refs after the fix, and explicit backend mapping sufficiency. | Full semantic consistency between every raw logical label/property and the claimed ontology realization. |
| 4. NL interpretation | No deterministic guarantee. | Plausibility, completeness, ambiguity coverage, top-1 accuracy, and execution equivalence to gold. |

Level 4 requires benchmark gold interpretations, answer/execution equivalence,
and empirical metrics such as top-1 accuracy and oracle@K. `c_sem` measures
distance between the selected query anchor and the model-claimed realization;
it does not independently recover the meaning of the NL question.

## 11. No-artifact negative controls

The offline controls establish:

- deleting `ontology.yaml` makes `DatasetBundle.load` raise
  `FileNotFoundError`; there is no hidden ontology fallback;
- an empty `prompt_schema_view` now raises before credentials or network I/O;
- query-slot candidates not present in visible terms are rejected before the
  request;
- unseen response ontology/entity IDs are rejected;
- absent backend term mappings produce explicit `MISSING` sufficiency and do
  not synthesize a representation;
- incomplete candidate slots trigger the configured explicit failure path;
- a schema-valid but NL-inconsistent relation label can still pass Levels
  1-3, intentionally demonstrating that validation does not prove Level 4.

Search of production source found no `Person`, `Ownership`, `Transfer`,
`PersonalAccount`, or `person-alice` constants in the live inference path.
They originate in the DatasetBundle. `src/xgap/experiments/results.py` contains
the older financial-risk smoke row shape, but it is unrelated to ontology
retrieval or model prompting.

## 12. Interpretation diversity

The historical request asked for 3 and received 3. All 3 parsed, type-checked,
lowered, and passed the old grounding check; all 3 were under epsilon. Under
the corrected typed-component rule, candidates 1 and 2 are grounding-valid
and candidate 3 is invalid.

There are two distinct `PathPatternQuery` structures: exact Account and broader
FinancialEntity target. Candidates 1 and 3 have identical `P`; they differ
only in `tau`, and candidate 3's attachment is invalid. Therefore the live run
provides two valid distinct interpretations after audit, not three.

The historical prompt did not explain why M candidates exist, reject
duplicates, or define admissible exact/relaxed alternatives. The minimal
prompt fix now asks for plausible semantically distinct readings and rejects
mere reformatting. No deterministic semantic deduplication or model-confidence
ranking was added; diversity quality remains empirical.

## 13. One-call / repair protocol

The successful run records `generation_calls=1`, `repair_calls=0`, request ID
`chatcmpl-65cb7c15-9507-9fa6-927b-65711b2bdfef`, latency
`22.685094833374023` seconds, and 2684/1474/4158 input/output/total tokens.

`generate_candidates` performs one normal transport call. Parsing failures in
JSON extraction, M10 parsing, grounded envelope shape, or an optional provider
response validator permit exactly one repair call; the repair adds the invalid
assistant response and one validation-error instruction. A second failure is
`repair_failed`. `UrllibOpenAICompatibleTransport` performs no retry loop, and
timeouts/provider errors fail immediately. Grounding visibility and M11
failures occur after this provider repair boundary and do not cause hidden
semantic regeneration.

Future request artifacts record one row per actual outbound generation or
repair call, including call kind and index.

## 14. Anti-leakage audit

Runtime question serialization deliberately retains only ID, text, split,
support class, source benchmark ID, and non-gold metadata. The runtime loader
copies ontology, aliases, entity catalog, backend mapping, and schema snapshot;
it does not retain `DatasetBundle` or `gold_alignments`.

`assert_no_gold_leakage` recursively rejects `gold_answers`,
`gold_logical_form`, `gold_alignments`, and `evaluation_labels` in runtime
questions, prompt views, and planner requests. The actual `questions.jsonl`,
`prompt_schema_view.jsonl`, raw response, grounding, and alignment artifacts
contain none of those fields. The view's ontology/schema/mapping hashes match
the run manifest. No hidden gold fallback was found.

The guard is key-based and is not a proof against semantic leakage introduced
manually into benignly named text. For the controlled bundle, direct artifact
inspection found no such leakage.

## 15. Reproducibility/artifact sufficiency

Historical successful run:

| Item | Status | Evidence/reason |
|---|---|---|
| Exact NL question | PASS | `questions.jsonl` |
| Exact system prompt | PASS | copied `prompt.json` plus hash |
| Exact bounded context | PASS | complete `prompt_schema_view.jsonl` plus hash |
| Exact JSON Schema delivered | FAIL | only hash/ref are copied; `structured_schema.json` is absent from the run |
| Exact model snapshot | PASS | model config and manifest |
| Exact temperature/top-p/token/cap/seed | PASS | model config and invocation metadata |
| Exact assembled messages and `response_format` | FAIL | no assembled request artifact; reconstruction requires implementation knowledge |
| Exact endpoint/timeout/provider extras | PASS | invocation metadata/manifest |
| Exact raw model response | PASS | `raw_model_responses.jsonl` |
| Exact parsed candidate | PASS | raw structured response plus `candidates.jsonl` |
| Exact grounding/alignment | PASS | grounding/query-slot/alignment artifacts |
| Exact validation and `c_sem` | PASS | `validation.jsonl` and physical artifacts |
| Logical plans | PASS | one artifact for every candidate |
| Selected physical plans/output | PASS | candidates 1 and 3; candidate 2 is correctly represented by trace/eligibility rather than a selected artifact |
| Exact source state | FAIL | commit is recorded but `dirty=true`; uncommitted source diff is not captured |

Consequently the exact historical request cannot be known from run artifacts
alone without reading code and guessing assembly. The audit reconstructed it
because the current artifacts and implementation still matched, but that is
not a sufficient experiment contract.

The required fix adds `llm_requests.jsonl`. Each row contains the sanitized
actual payload, URL, timeout, call index/kind, and canonical payload hash; the
raw invocation stores matching request hashes. It includes the full system and
user messages, embedded schema, `response_format`, model, and parameters, but
never the API key. Fake-HTTP integration verifies byte-equivalent JSON objects
against the transport payload. A new live run is required to make the run-level
row PASS; the historical run remains an honest pre-fix artifact. That required
run was subsequently completed as described below.

The credentialed post-fix smoke satisfies that requirement. It records one
generation request in `llm_requests.jsonl` with payload hash
`a50b59ab2eb9f3d058d71daf1914e8df7cc85340d34af544ba36c7fa0fa888ee`.
The same hash appears in `raw_model_responses.jsonl`; the payload contains the
new semantic system prompt, the complete user-message schema/context, model
`qwen3-max-2026-01-23`, `response_format={"type":"json_object"}`, and no
authorization header or API-key value. For this post-fix run, exact JSON Schema
delivery and exact assembled request reconstruction are PASS. A final paper
run should still start from a clean recorded commit rather than a dirty tree.

## 16. Findings classified

| Class | ID | Finding | Disposition |
|---|---|---|---|
| BLOCKER | B-1 | The changed prompt/request required one credentialed post-fix smoke. | Resolved: 1 live test passed in 33.64 seconds and the exact request artifact was inspected. |
| CORRECTNESS | C-1 | `component_ref` accepted any non-empty string; historical candidate 3 attached a class to an edge and was selected. | Fixed with component existence and kind validation plus regression tests. |
| CORRECTNESS | C-2 | Empty ontology/schema mappings could reach request assembly. | Fixed with pre-network bounded-view validation. |
| REPRODUCIBILITY | R-1 | The exact historical assembled request and embedded schema were not persisted. | Fixed for future runs with `llm_requests.jsonl`; historical run remains FAIL. |
| EXPERIMENT-DESIGN | E-1 | Historical semantic instructions and diversity guidance were underspecified. | Minimal zero-shot contract added; no examples/tuning. |
| EXPERIMENT-DESIGN | E-2 | Legal, grounded output can still be NL-inconsistent; no Level 4 oracle exists in M12-B. | Must be measured in later benchmark evaluation, not patched with deterministic guessing. |
| EXPERIMENT-DESIGN | E-3 | Backend hints expose representations, not a complete capability profile, so unsupported patterns may still be proposed. | Existing deterministic validation/planning rejects them; broader prompt filtering is follow-up work. |
| NON-BLOCKING | N-1 | Static schema leaves scalar `condition` shape generic and dynamic IDs/component refs as strings. | Parser/runtime checks remain authoritative; consider a future schema-only refinement. |
| NON-BLOCKING | N-2 | Confidence/rationale are uncalibrated metadata and the live model has no supported seed. | Record and evaluate; do not feed them into M11. |
| NON-BLOCKING | N-3 | One invalid candidate currently rejects grounding for the response rather than salvaging siblings. | Explicit failure is truthful; per-candidate repair/salvage would be a future policy change. |

## 17. Minimal recommended fixes

Implemented in this audit:

1. Persist every actual sanitized outbound payload in `llm_requests.jsonl`,
   with URL, timeout, generation/repair index, and hash.
2. Reject absent/empty/malformed ontology context before a provider call.
3. Validate every realization against a real typed `PathPatternQuery`
   component.
4. Keep zero-shot but clarify PathPatternQuery semantics and require distinct
   semantic candidates.
5. Add exact-request, no-artifact, invalid-component, missing-artifact, and
   schema-valid/NL-wrong controls.

The one-question DashScope smoke was rerun with credentials. It made one
generation call, made no repair call, returned three candidates, and completed
one physical plan. All slot realizations used real kind-compatible components.
Candidates 1 and 2 were explicitly rejected by existing M5 type checking;
candidate 3 passed type checking, lowering, grounding, mapping, `c_sem`, M11
planning, and physical compilation. The exact request artifact is present and
matches the invocation hash.

Do not add few-shot examples unless repeated post-fix failures identify a
specific error mode that the zero-shot contract cannot resolve. Never use
evaluation questions as examples.

## 18. Explicit things that should NOT be changed

- Do not change `PathPatternQuery`, path-algebra semantics, deterministic
  lowering, or existing formatted logical plans.
- Do not redesign M11 BnB, `c_sem`, objective scoring, cost estimation, or
  top-K selection as part of this audit.
- Do not let confidence/rationale alter semantic deviation or physical search.
- Do not let the LLM emit logical operators, native Cypher/SPARQL/GQL,
  physical plans, backend placement, or costs.
- Do not add automatic ontology induction, OWL/DL reasoning, hidden fallback
  terms, or gold-data access.
- Do not add a large few-shot set or begin prompt/model tuning.
- Do not implement M12-C calibration, M12-D baselines/ablations, datasets, or
  KGQA evaluation here.
- Do not modify the historical
  `docs/report/logical_lowering_analysis.md`.
