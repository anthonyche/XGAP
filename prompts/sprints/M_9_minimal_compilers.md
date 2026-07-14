# Sprint: M9 Minimal Compilers For Backend MVP

## Goal

Implement the smallest safe compiler layer that closes an end-to-end
backend MVP loop for a bounded XGAP path/GPC fragment:

```text
validated structured path query or logical plan
  -> M8 capability check
  -> native query artifact
  -> M7 backend execution harness
  -> normalized backend result
```

M9 is intentionally minimal. It does not introduce optimization
objectives, semantic-deviation scoring, natural-language planning, or
KGQA evaluation.

## Required Preflight

Before implementation:

1. Read `AGENTS.md`.
2. Read `docs/architecture.md`.
3. Read `docs/roadmap.md`.
4. Read `docs/status.md`.
5. Read `docs/operator_semantics.md`.
6. Read `docs/decisions.md`.
7. Read `docs/m8_backend_capability_preflight.md`.
8. Read this sprint prompt.
9. Inspect:
   - `src/xgap/compilers/base.py`
   - `src/xgap/compilers/cypher.py`
   - `src/xgap/compilers/sparql.py`
   - `src/xgap/compilers/gql.py`
   - `src/xgap/algebra/ops.py`
   - `src/xgap/algebra/conditions.py`
   - `src/xgap/algebra/validation.py`
   - `src/xgap/algebra/pretty.py`
   - `src/xgap/pattern/ast.py`
   - `src/xgap/pattern/lowering.py`
   - `src/xgap/backends/capabilities.py`
   - `src/xgap/backends/compatibility.py`
   - `descriptors/backends/*.yaml`
   - existing compiler placeholders, tests, examples, and acceptance script

Then report:

- current project status;
- current milestone;
- exact M9 fragment to compile;
- target backends/languages;
- expected files to add;
- expected files to modify;
- forbidden changes;
- acceptance criteria.

Do not implement before reporting the plan.

## M9 Scope

M9 compiles only a small, bounded, path-centric fragment.

The intended first supported fragment is:

- already validated `PathPatternQuery` or already validated
  path-algebra `LogicalPlan`;
- `OUT` directed relationships only;
- fixed-length path expressions compiled from `Rel` and `Seq`;
- node-label predicates;
- edge-label predicates;
- scalar property predicates that are already implemented by XGAP
  conditions;
- source and target descriptors that lower to `Selection`;
- row-oriented native results suitable for the M7 backend harness.

M9 may support a narrow subset of:

- `Nodes(G)`
- `Edges(G)`
- `Selection`
- `Join`

M9 may support `Union` only if the emitted native query result shape is
identical across branches and deterministic duplicate handling is
documented and tested.

M9 must treat these as unsupported unless explicitly implemented and
tested in this sprint:

- `Recursive`
- `GroupBy`
- `OrderBy`
- `Projection` selector semantics over `SolutionSpace`
- M6 focused binding operators
- `FocusedQuantifiedPatternQuery`
- reverse or undirected edge lowering
- optional or bounded regex placeholders
- arbitrary conjunctive graph patterns
- arbitrary user-visible joins outside the path fragment

## Target Languages

M9 should implement:

- minimal Cypher compiler support for Neo4j;
- minimal SPARQL compiler support for Fuseki.

GQL remains a compiler boundary placeholder in M9 unless the sprint is
explicitly expanded. It must fail explicitly with an unsupported report
or `NotImplementedError`.

## Allowed Changes

You may add:

- `src/xgap/compilers/artifacts.py`
- `src/xgap/compilers/errors.py`
- `src/xgap/compilers/features.py`
- `tests/test_compiler_boundaries.py`
- `tests/test_cypher_compiler.py`
- `tests/test_sparql_compiler.py`
- `examples/compiler_mvp_demo.py`
- `docs/m9_minimal_compilers.md`
- `prompts/sprints/M_9_minimal_compilers.md`

You may modify:

- `src/xgap/compilers/base.py`
- `src/xgap/compilers/cypher.py`
- `src/xgap/compilers/sparql.py`
- `src/xgap/compilers/gql.py`
- `src/xgap/compilers/__init__.py`
- `src/xgap/backends/capabilities.py`, only for additive integration
  helpers if needed;
- `src/xgap/backends/compatibility.py`, only for additive integration
  helpers if needed;
- backend descriptors, only if M9 support levels need to be narrowed or
  annotated after implementation;
- `docs/architecture.md`
- `docs/roadmap.md`
- `docs/status.md`
- `docs/decisions.md`
- `scripts/run_acceptance.sh`, only if adding the M9 demo to acceptance.

## Forbidden Changes

Do not implement:

- optimizer rules;
- cost estimation;
- optimization objectives;
- semantic-deviation scoring;
- ontology reasoning;
- bounded planning;
- dominance pruning;
- top-K selection;
- LLM candidate generation;
- natural-language parsing;
- disambiguation;
- KGQA evaluation;
- full GPC;
- arbitrary conjunctive graph-pattern matching;
- M6 quantified-pattern backend compilation unless explicitly approved
  in a later sprint.

Do not introduce logical operator names outside the XGAP vocabulary.
Forbidden examples include:

- `NodeScan`
- `EntityLookup`
- `EdgeExpand`
- `PathExpand`
- `Filter`
- `Aggregate`
- `Rank`
- `Project`

Do not change M0-M8 semantics to make compiler tests pass.

Do not silently emit an empty query or empty result for unsupported
features. Unsupported compilation must fail explicitly.

## Implementation Requirements

### 1. Compiler Artifact Boundary

Use the M8 compiler boundary records where appropriate:

- `CompilerInputSpec`
- `CompilerOutputSpec`
- `CompilerFailureSpec`
- `QueryArtifact`
- `CompatibilityReport`

Compilation functions should return a native `QueryArtifact` or raise a
clear compiler error carrying unsupported-feature information.

### 2. Capability Check First

Before emitting native query text, M9 must check the target backend
profile through the M8 compatibility layer.

The compiler must not proceed when a required feature is unsupported.

Conditional support may proceed only when the compiler has explicitly
implemented the condition and documents the assumption.

### 3. Deterministic Native Query Generation

Generated Cypher and SPARQL must be deterministic:

- stable variable names;
- stable clause ordering;
- stable projection ordering;
- stable formatting;
- no dependence on Python object identity or dictionary iteration order
  unless sorted.

### 4. Minimal Cypher Fragment

The Cypher compiler should support the agreed M9 path fragment using
Neo4j property-graph vocabulary:

- node labels;
- relationship types;
- scalar property predicates;
- fixed-length `OUT` paths;
- row bindings for source, target, and selected path values as needed by
  tests.

It must not compile unsupported `Recursive`, `SolutionSpace`, or M6
binding constructs.

### 5. Minimal SPARQL Fragment

The SPARQL compiler should support the agreed M9 path fragment using
the dataset mapping assumptions documented by M9.

Because Fuseki/RDF does not expose XGAP `PathSet` path identity in M8,
the M9 SPARQL fragment should be row-oriented and must document any
mapping assumptions for:

- RDF type or label representation;
- predicates as edge labels;
- literal property predicates;
- projected row bindings.

It must not claim full XGAP `PathSet` preservation unless that behavior
is implemented and tested.

### 6. Unsupported Feature Reporting

Unsupported compilation must report:

- target backend id;
- target language;
- unsupported feature id;
- support level;
- reason;
- future milestone hint when applicable.

Tests must verify unsupported reports for:

- recursive modes outside M9;
- `GroupBy`, `OrderBy`, and selector `Projection`;
- M6 focused binding operators;
- `FocusedQuantifiedPatternQuery`;
- GQL compilation in M9 if not implemented.

### 7. Full-Chain MVP Demo

Add a minimal compiler demo that shows:

```text
structured path query or logical path fragment
  -> validate/type-check
  -> lower if needed
  -> capability check
  -> compile to Cypher and/or SPARQL QueryArtifact
```

If the demo does not require live services, include it in
`scripts/run_acceptance.sh`.

Live Neo4j/Fuseki execution remains optional and must stay skipped unless
`XGAP_RUN_BACKENDS=1`.

## Tests

Add tests for:

- compiler boundary record use;
- capability check before compilation;
- deterministic Cypher output for the supported M9 fragment;
- deterministic SPARQL output for the supported M9 fragment;
- explicit unsupported failures for out-of-scope operators;
- GQL unsupported boundary if GQL is not implemented;
- no live backend requirement in default pytest.

Required test commands:

```bash
python -m pytest tests/test_compiler_boundaries.py tests/test_cypher_compiler.py tests/test_sparql_compiler.py
python -m pytest
./scripts/run_acceptance.sh
```

Optional live test command, only when services are running:

```bash
PYTHONPATH=src XGAP_RUN_BACKENDS=1 python -m pytest tests/test_backend_live.py
```

## Documentation Updates

Update:

- `docs/status.md`
- `docs/roadmap.md`
- `docs/architecture.md`
- `docs/decisions.md`
- `docs/m9_minimal_compilers.md`

Document:

- exact M9 supported fragment;
- Cypher mapping assumptions;
- SPARQL/RDF mapping assumptions;
- unsupported features;
- compiler artifact boundary;
- why M9 is not an optimizer, planner, semantic-deviation layer, or KGQA
  evaluation layer.

## Acceptance Criteria

M9 is DONE only if:

- Cypher compiler supports the agreed minimal path/GPC fragment;
- SPARQL compiler supports the agreed minimal path/GPC fragment;
- GQL either supports an explicitly defined minimal fragment or fails
  explicitly as unsupported;
- compilers check M8 backend profiles before emitting native artifacts;
- unsupported features fail explicitly and are tested;
- generated native query artifacts are deterministic;
- default pytest does not require live backend services;
- `python -m pytest` passes;
- `./scripts/run_acceptance.sh` passes;
- docs/status.md is updated;
- no optimizer, semantic-deviation, planner, LLM, ontology, top-K, or
  KGQA functionality is added;
- no M0-M8 semantics are changed.
