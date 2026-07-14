# M10 LLM Planner Boundary + Structured Candidate Interface

## Status

M10 defines the interface between future LLM-based natural-language
planning and XGAP's deterministic path/GPC stack.

M10 does not connect a concrete model. It does not add Qwen, OpenAI,
DashScope, vLLM, local-model, or LoRA integration.

## Boundary

The LLM boundary may propose only controlled structured candidate JSON.
That JSON must parse into an existing `PathPatternQuery`.

The LLM boundary must not emit native Cypher, SPARQL, or GQL. It must
not emit logical operators directly and must not participate in
deterministic lowering, validation, compilation, optimization, backend
execution, semantic-deviation scoring, ontology reasoning, or KGQA
evaluation.

The intended flow is:

```text
natural-language question
  -> structured candidate JSON
  -> PathPatternQuery parser
  -> type_check_path_pattern
  -> lower_path_pattern
  -> validate_plan
  -> M9 compiler
  -> optional backend execution
```

## Implemented Records

M10 introduces:

- `PlannerRequest`;
- `PlannerCandidate`;
- `PlannerResponse`;
- `CandidateValidationReport`;
- `StructuredCandidateProvider`;
- `MockStructuredCandidateProvider`;
- `PlannerSchemaError`.

These records are small dataclasses with JSON-serializable boundaries.

## Controlled JSON

The controlled JSON represents:

- source and target `NodePattern` descriptors;
- regular path expressions using `rel`, `seq`, `alt`, `plus`, `star`,
  `optional`, and `bounded` JSON tags that map to existing M5 AST
  classes;
- `EdgePattern` descriptors with existing `Direction` values;
- selector kind and optional `k`;
- path restrictor;
- optional existing scalar condition JSON.

Unsupported M5 placeholders such as `optional` and `bounded` can parse
into the existing AST, but deterministic candidate validation reports
their unsupported lowering stage explicitly.

## Provider Protocol

`StructuredCandidateProvider` has one method:

```python
generate_candidates(request: PlannerRequest) -> Mapping[str, Any]
```

M10 intentionally has no default provider. `plan_from_question()` raises
`NotImplementedError` unless an explicit provider is passed.

The included `MockStructuredCandidateProvider` is for unit tests and
local demos only.

Future live providers should be configured externally, for example:

```text
XGAP_LLM_PROVIDER=openai_compatible
XGAP_LLM_BASE_URL=...
XGAP_LLM_MODEL=...
XGAP_LLM_API_KEY=...
```

Those environment variables are documented as future configuration
shape only. M10 does not read them and does not call live model services.

## Rejected In M10

M10 rejects native query fields in planner candidates, including:

- `native_query`;
- `cypher`;
- `sparql`;
- `gql`;
- `query_text`.

This prevents a future provider from bypassing `PathPatternQuery`,
type checking, lowering, validation, and M9 capability/compiler checks.

## Verification

Required checks:

```bash
python -m pytest tests/test_llm_boundary.py
python examples/llm_boundary_demo.py
python -m pytest
./scripts/run_acceptance.sh
```

Default pytest does not require a live LLM or backend service.
