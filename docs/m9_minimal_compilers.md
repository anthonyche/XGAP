# M9 Minimal Compilers For Backend MVP

## Status

M9 implements the first deterministic native-query compiler slice after
the M8 capability-profile preflight.

It closes a minimal backend MVP loop:

```text
validated PathPatternQuery or logical path fragment
  -> M8 capability check
  -> native QueryArtifact
  -> optional M7 backend harness execution
```

M9 does not implement optimization, semantic-deviation scoring,
ontology reasoning, bounded planning, dominance pruning, top-K
selection, LLM candidate generation, KGQA evaluation, or full
logical-plan-to-native-query coverage.

## Supported Fragment

M9 compiles a bounded row-oriented path/GPC fragment:

- `Nodes(G)`;
- `Edges(G)`;
- `Selection`;
- path-chain `Join`;
- fixed-length `OUT` path fragments;
- node-label predicates;
- edge-label predicates;
- scalar property equality and numeric comparisons already represented
  by XGAP conditions;
- `PathPatternQuery` only when the selector is `ALL`, because no
  selector-style `SolutionSpace` semantics are compiled in M9.

Compilation accepts already validated logical plans. When a
`PathPatternQuery` is supplied, M9 type-checks it and lowers only the
ALL-selector path fragment needed for row-oriented native output.

## Capability Boundary

Every compiler call checks the target backend profile before native
query text is emitted.

The compiler proceeds through conditional M8 feature entries only for
the conditions implemented in M9:

- row-oriented native output;
- fixed-length `OUT` path chains;
- labels and scalar property predicates;
- documented Cypher or SPARQL mapping assumptions.

Unsupported or undeclared features raise `UnsupportedCompilationError`
with a `CompilerFailureSpec`.

## Cypher Mapping

The Neo4j compiler emits Cypher `QueryArtifact` objects.

Mapping assumptions:

- Neo4j node labels represent XGAP node labels;
- Neo4j relationship types represent XGAP edge labels;
- node and relationship properties represent XGAP scalar properties;
- output is row bindings with `source`, `target`, `nodes`, and `edges`
  columns;
- native rows are not claimed to be XGAP `PathSet` objects.

## SPARQL Mapping

The Fuseki compiler emits SPARQL `QueryArtifact` objects.

Mapping assumptions:

- the active DatasetBundle backend mapping is the sole source of RDF class,
  predicate, and property IRIs;
- compiler tokens resolve through typed canonical term mappings; missing or
  ill-typed mappings fail explicitly;
- RDF type triples represent node-label predicates;
- output is row bindings with `source`, `target`, node variables, and
  edge-predicate variables;
- edge property predicates are unsupported because M9 does not define
  RDF edge reification;
- SPARQL output is not claimed to preserve native XGAP `PathSet` path
  identity.

M9 does not own a generic or dataset-specific RDF namespace. A different
dataset changes native IRIs through its mapping artifact, without a compiler
source change.

## Unsupported In M9

M9 explicitly rejects:

- `Union`;
- `Recursive`;
- `GroupBy`;
- `OrderBy`;
- selector-style `Projection`;
- M6 focused binding operators;
- `FocusedQuantifiedPatternQuery`;
- `PathPatternQuery` selectors other than `ALL`;
- reverse and undirected path-pattern edges;
- optional or bounded regex placeholders;
- boolean `OR` and `NOT` conditions;
- path-length conditions;
- GQL compilation.

GQL remains an explicit unsupported compiler boundary in M9.

## Verification

Required checks:

```bash
python -m pytest tests/test_compiler_boundaries.py tests/test_cypher_compiler.py tests/test_sparql_compiler.py
python examples/compiler_mvp_demo.py
python -m pytest
./scripts/run_acceptance.sh
```

Live Neo4j and Fuseki execution remains optional and gated by the M7
backend harness. Default pytest does not require live backend services.
