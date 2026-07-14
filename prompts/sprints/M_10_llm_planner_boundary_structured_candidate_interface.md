# Sprint: M10 LLM Planner Boundary + Structured Candidate Interface

## Goal

Define the boundary between natural-language planning and XGAP's
deterministic path/GPC stack.

M10 does not connect a concrete LLM provider. It prepares typed
interfaces and a controlled JSON protocol so that a future model can
propose `PathPatternQuery` candidates without participating in
deterministic lowering, validation, compilation, optimization, or
execution.

The intended flow is:

```text
natural-language question
  -> structured candidate JSON
  -> deterministic PathPatternQuery parser
  -> type_check_path_pattern
  -> lower_path_pattern
  -> validate_plan
  -> M9 compiler
  -> optional backend execution
```

## Scope

M10 supports:

- typed planner request and response records;
- a minimal provider protocol for structured candidate generation;
- a mock provider for tests and local demos;
- controlled JSON parsing into `PathPatternQuery`;
- deterministic candidate type checking, lowering, and plan validation
  helpers;
- documentation of future provider configuration without implementing
  provider-specific clients.

The controlled JSON must represent only the existing M5
`PathPatternQuery` AST and existing scalar conditions.

## Non-Goals

Do not implement:

- concrete Qwen, OpenAI, DashScope, vLLM, or local model clients;
- LoRA or model training;
- prompt optimization;
- natural-language parsing outside the provider boundary;
- semantic-deviation scoring;
- optimizer rules;
- cost estimation;
- bounded planning;
- dominance pruning;
- top-K selection;
- ontology reasoning;
- KGQA evaluation;
- direct Cypher, SPARQL, or GQL generation by an LLM.

## Acceptance Criteria

- Planner request, response, candidate, and validation records are
  JSON-serializable.
- Controlled JSON parses deterministically into `PathPatternQuery`.
- Invalid JSON fails explicitly.
- `plan_from_question()` requires an explicit provider in M10.
- Mock provider tests can generate candidates without a live LLM.
- Candidate validation can run type checking, lowering, and plan
  validation without calling a provider, compiler, backend, optimizer,
  or LLM.
- Default pytest does not require live model services.
- Docs and status are updated.
- `python -m pytest` passes.
- `./scripts/run_acceptance.sh` passes.
