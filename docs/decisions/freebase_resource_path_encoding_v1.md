# INT-1 planned resource-triple PathSet encoding

Status: implementation contract after INT-0; **not yet implemented or tested**.
Motivation: R-E/E1 independent answers and R-C/E2 same-meaning execution need the
ordinary semantic planner to compile the existing raw-RDF/Neo4j mirror snapshot.
This is a representation adapter, not a new semantic operator or a fact rewrite.

## Scope and identity

In a declared default RDF graph, each distinct URI triple `(s,p,o)` is one directed
logical edge. The existing Neo4j loader uses `MERGE` on those triples; RDF has set
semantics. Duplicate input occurrences fold, but different predicates between
the same endpoints remain distinct edges. This does not model arbitrary property
multigraph edge multiplicity, named graphs, blank nodes or literal path nodes.

Define an injective edge identity in the shared Python decoder:

```
E(s,p,o) = "rdf-triple-v1:" + canonical_json([s,p,o])
```

Do not use Neo4j internal IDs, row ordinals or predicate alone. OUT uses the
traversed endpoints in order; IN reverses them before forming `(s,p,o)`, so both
directions identify the same stored edge. Preserve IRI lexical forms exactly.
Validate nodes against the declared canonical resource namespace/ID domain.

The first adapter accepts the existing fixed `Rel/Seq` paths of one to three
resource edges, `ALL`, and the explicitly checked condition/restrictor subset.
It must preserve anchor/type/node-inequality constraints and answer position.
Unsupported scalar, edge-property, Boolean or path-mode cases return unavailable;
they remain in the formal population. Do not silently broaden or relax meaning.

## Minimal implementation boundary

1. Add an explicit resource-triple encoding declaration to `SemanticBackend`
   and its path options. Bind snapshot/encoding identity, mirror node/relationship
   labels, IRI/predicate properties and RDF class predicate. Existing defaults
   continue through their current compiler paths.
2. A bounded native row adapter returns complete `n0..nk`, `e1..ek`, and length.
   Fuseki reuses directed RDF row compilation (edge columns carry predicate IRIs),
   with URI-only checks. Neo4j reuses the existing mirror shape/condition logic,
   returning node IRIs and relationship predicates, not answer-only rows.
   Use independent MATCH clauses so Cypher does not impose unintended edge
   uniqueness on WALK. Do not import the experiment module into core compilation;
   move only genuinely shared, needed logic if extraction is necessary.
3. A declared input-model branch in native path decoding validates all columns,
   length, types, directions and identity, then constructs ordinary Path/PathSet
   values for existing selection, scheduling and P1. Bound result rows with an
   overflow sentinel; overflow is failure, never a truncated successful answer.

Current row projection uses one namespace for nodes and edges. The new edge IDs
are not Freebase MIDs: reject edge projections for this first encoding unless a
separate edge-identity projection contract is implemented. Node/endpoint projection
must still return the correct typed entity IRI. Reuse of an answer-only legacy
plan is not an implementation of Traverse's PathSet contract.

## Ptime and guarantee boundary

With fixed maximum three hops, query/mapping description length L and A explicit
local backend alternatives, compilation is polynomial (target O(A L)); no joint
placement enumeration is introduced. Decoding is linear in returned byte volume
B, plus PathSet sorting/deduplication (O(R log R) path comparisons for R rows),
with O(B) storage. Explain any validation work beyond these bounds in code review.
These are compiler/decoder bounds. They do not bound observed backend latency;
fixed-three-hop answer enumeration may still be O(N cubed) for N resource facts.
P1's existing objective and conditional solution certificates are unchanged.

## Small acceptance gate

- OUT/IN one-hop over both encodings: equal complete paths, same stored edge ID,
  correct first/last typed entity projection.
- Duplicate triples and two predicates sharing endpoints: duplicate folds;
  distinct predicate paths survive.
- Two/three-hop mixed direction and returning to start: WALK and explicit SIMPLE
  constraints differ exactly as specified; no hidden Cypher uniqueness.
- Literal/blank-node/missing-column/overflow output and unsupported scalar input:
  explicit failure/unavailable with no successful partial answers.

Only affected module cases and one tiny real Neo4j/Fuseki integration slice are
needed after implementation. Do not repeat A1–A3 or the broad regression suite.
Then replay both original INT-0 programs; actual GrailQA answers require a frozen,
query-independent fact snapshot and its load receipts. The annotated anchor-type
constraint versus official SPARQL remains an explicit equivalence check. Do not
claim full GrailQA integration from these two one-source queries.
