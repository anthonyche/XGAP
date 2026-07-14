# Sprint: M8 Backend Capability Profile + Compiler Boundary Preflight

## Goal

Upgrade M7 backend descriptor capabilities from descriptive metadata into
program-checkable capability profiles, and define the compiler boundary
for the future minimal full-chain MVP.

M8 does not compile logical plans. It decides whether a backend can
theoretically support a given XGAP path/GPC logical fragment, and it
defines the typed input, output, and unsupported-report records that a
future compiler will use.

## Required Preflight

Before implementation:

1. Read `AGENTS.md`.
2. Read `docs/architecture.md`.
3. Read `docs/roadmap.md`.
4. Read `docs/status.md`.
5. Read `docs/operator_semantics.md`.
6. Read `docs/decisions.md`.
7. Read `docs/m8_backend_capability_preflight.md`.
8. Inspect:
   - `descriptors/backends/*.yaml`
   - `src/xgap/infrastructure/descriptors.py`
   - `src/xgap/infrastructure/runtime.py`
   - `src/xgap/backends/registry.py`
   - `src/xgap/backends/protocol.py`
   - `src/xgap/experiments/backend_smoke.py`
   - `src/xgap/algebra/ops.py`
   - `src/xgap/algebra/validation.py`
   - `src/xgap/pattern/lowering.py`
   - `src/xgap/pattern/quantified_lowering.py`
   - existing backend infrastructure tests

Then report:

- current project status
- current milestone
- acceptance criteria
- exact files expected to be modified
- exact files expected to be added
- unsupported-feature boundary

Do not implement before reporting the plan.

## M8 Questions

M8 must answer:

1. Which XGAP path/GPC fragments does Neo4j support?
2. Which XGAP path/GPC fragments does Fuseki support?
3. Which M0-M6 logical constructs can be safely compiled later?
4. Which constructs must explicitly return unsupported?
5. What is the format of compiler input, output, and failure reports?

## Allowed Changes

You may add:

- `src/xgap/backends/capabilities.py`
- `src/xgap/backends/compatibility.py`
- `tests/test_backend_capabilities.py`
- `tests/test_backend_compatibility.py`
- `docs/m8_backend_capability_preflight.md`
- `prompts/sprints/M_8_backend_capability_profile_compiler_boundary_preflight.md`

You may modify:

- `descriptors/backends/reference_evaluator.yaml`
- `descriptors/backends/neo4j.yaml`
- `descriptors/backends/fuseki.yaml`
- `src/xgap/infrastructure/descriptors.py`, only if descriptor validation needs additive helpers
- `src/xgap/backends/registry.py`, only if registry integration needs additive helpers
- `docs/architecture.md`
- `docs/roadmap.md`
- `docs/status.md`
- `docs/decisions.md`

## Forbidden Changes

Do not implement:

- logical-plan-to-native-query compilation
- Cypher compiler logic
- SPARQL compiler logic
- GQL compiler logic
- optimizer rules
- cost estimation
- semantic-deviation scoring
- ontology reasoning
- bounded planning
- dominance pruning
- top-K selection
- LLM candidate generation
- KGQA evaluation
- arbitrary conjunctive graph pattern support
- backend-specific logical operator vocabulary

Do not modify:

- M0-M6 logical operator semantics
- `PathPatternQuery` lowering semantics
- `FocusedQuantifiedPatternQuery` lowering semantics
- reference evaluator semantics
- existing M7 native backend smoke harness semantics

All unsupported future behavior must return explicit unsupported reports.
Never silently return empty support results for unimplemented behavior.

## Implementation Requirements

### 1. Capability Profile Data Model

Add typed dataclasses for capability profiles.

Required public objects:

- `SupportLevel`
  - `SUPPORTED`
  - `CONDITIONAL`
  - `UNSUPPORTED`
- `SupportReason`
- `FeatureSupport`
- `BackendCapabilityProfile`
- `CompatibilityReport`
- `UnsupportedFeature`
- `CompilerInputSpec`
- `CompilerOutputSpec`
- `CompilerFailureSpec`

The objects must be JSON-serializable and must not depend on Neo4j or
Fuseki drivers.

### 2. XGAP Feature Vocabulary

Capability features must use XGAP path/GPC vocabulary.

Represent support for:

- graph model
- node labels
- edge labels
- scalar property predicates
- path result model
- row result model
- `Nodes(G)`
- `Edges(G)`
- `Selection`
- `Union`
- `Join`
- `Recursive` by mode:
  - `WALK`
  - `TRAIL`
  - `ACYCLIC`
  - `SIMPLE`
  - `SHORTEST`
- `GroupBy`
- `OrderBy`
- `Projection`
- M5 `PathPatternQuery`
- M6 `FocusedQuantifiedPatternQuery`
- M6 focused binding layer:
  - `BindingRelation`
  - `BindNode`
  - `BindEdge`
  - `BindingJoin`
  - `BindingProject`
  - `QuantifiedCheck`
  - `AntiSemiJoin`
  - `FocusProjection`

M8 may mark features unsupported or conditional. It must not fake support.

### 3. Neo4j Profile

Update `descriptors/backends/neo4j.yaml` with a program-checkable profile.

Neo4j should be expected to support a small future MVP fragment around:

- directed labeled property graph model
- native Cypher row outputs
- node labels
- relationship types as edge labels
- scalar property predicates
- basic path-centric patterns

Recursive modes, selector semantics, and M6 quantified semantics must be
marked carefully as conditional or unsupported unless M8 can state a
clear and testable support boundary.

### 4. Fuseki Profile

Update `descriptors/backends/fuseki.yaml` with a program-checkable profile.

Fuseki should be expected to support a small future MVP fragment around:

- RDF graph model
- SPARQL row bindings
- IRI predicates as edge labels
- literal property predicates where represented in RDF
- basic path-centric query shapes

Property-graph-specific labels, path object return semantics, selector
semantics, and M6 quantified semantics must be marked carefully as
conditional or unsupported unless M8 can state a clear and testable
support boundary.

### 5. Reference Evaluator Profile

Update `descriptors/backends/reference_evaluator.yaml`.

The reference evaluator profile should indicate support for implemented
M0-M6 in-memory semantics. It is not a native backend compiler target.

### 6. Compatibility Checker

Add a checker that can answer:

```text
check_backend_support(profile, feature_request) -> CompatibilityReport
```

The checker must:

- return deterministic results;
- distinguish supported, conditional, and unsupported;
- include backend id;
- include feature id;
- include reason strings;
- include blocking unsupported features;
- never compile a query;
- never call backend clients;
- never call the evaluator;
- never call optimizer, LLM, planner, or cost model.

### 7. Compiler Boundary Records

Define typed records for future compiler boundaries:

- compiler input:
  - validated logical plan identity or feature summary
  - target backend id
  - target language
  - expected result model
- compiler output:
  - `QueryArtifact`
  - semantic assumptions
  - target backend id
- failure report:
  - backend id
  - language
  - unsupported feature
  - reason
  - support level
  - future milestone hint

These records are schemas only in M8. They must not compile plans.

### 8. Minimal MVP Closure Expectation

M8 should prepare the smallest credible full-chain MVP path:

```text
validated path/GPC logical fragment
  -> capability check
  -> future compiler boundary
  -> native query artifact
  -> M7 backend execution harness
  -> normalized result
```

M8 itself stops at capability check and boundary records.

It is acceptable that M8 has no XGAP-defined optimization objective and
no semantic-deviation metric. Those remain future work.

## Tests

Add tests for:

- loading updated descriptor capability profiles;
- profile serialization;
- support-level parsing;
- Neo4j supported/conditional/unsupported feature checks;
- Fuseki supported/conditional/unsupported feature checks;
- reference evaluator support checks;
- unsupported reports for M6 focused quantified constructs on backends if not supported;
- compiler boundary record serialization;
- no live backend requirement in default pytest.

Required test commands:

```bash
python -m pytest tests/test_backend_capabilities.py tests/test_backend_compatibility.py
python -m pytest
./scripts/run_acceptance.sh
```

Live Neo4j/Fuseki tests remain optional and must still be skipped unless
`XGAP_RUN_BACKENDS=1`.

## Documentation Updates

Update:

- `docs/status.md`
- `docs/roadmap.md`
- `docs/architecture.md`
- `docs/decisions.md`
- `docs/m8_backend_capability_preflight.md`

Document:

- M8 capability profile schema
- Neo4j profile summary
- Fuseki profile summary
- reference evaluator profile summary
- compiler boundary records
- unsupported-feature reporting
- explicit non-goals

## Acceptance Criteria

M8 is DONE only if:

- descriptor `capabilities` are program-checkable;
- Neo4j, Fuseki, and reference evaluator profiles load;
- compatibility checker returns deterministic reports;
- supported, conditional, and unsupported cases are tested;
- compiler boundary records are typed and serializable;
- default pytest does not require live backend services;
- `python -m pytest` passes;
- `./scripts/run_acceptance.sh` passes;
- docs/status.md is updated;
- no compiler implementation is added;
- no optimizer, semantic-deviation, planner, LLM, ontology, top-K, or KGQA functionality is added;
- no M0-M6 semantics are changed.
