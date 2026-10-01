# D195: typed fixed directed native rows

## Frozen implementation scope

Add an explicit compiler and runtime-fragment adapter for typed `Rel`/`Seq`
`OUT`/`IN`, ALL-selector path rows on Cypher and mapped SPARQL. Do not call or
modify M5 lowering, add a path-algebra operator, invert stored data, change
legacy compilation defaults, or migrate a frozen GrailQA experiment.

The profile preserves traversal-position `source`, `target`, node and edge
bindings even when a stored edge points backwards. Fixed expressions retain
M5's descriptor/concatenation semantics: restrictors affect recursive nodes,
not bare Rel/Seq. Explicit `NodeNotEquals` constraints (including those added
by the separate canonical SIMPLE normalizer) are enforced, never synthesized
or removed here. Pattern variable names are annotations, not assignments.

Separate MATCH clauses prevent Cypher's implicit per-pattern relationship
uniqueness from silently excluding repeated-edge fixed walks. SPARQL uses
explicit oriented triples; its edge columns are predicate IRIs, not Neo4j
relationship identities. This is a native row-binding profile, not PathSet
preservation, full GPC, full KGQA, or measured backend admission.

Acceptance requires deterministic exact-position compilation, strict mapping
and capability checks, constraint preservation, explicit unsupported outcomes,
unchanged legacy tests, and execution of emitted SPARQL against an independent
local query engine. Real Neo4j/Fuseki acceptance remains separately live-gated.
No CWRU submission, model call, experiment authority or new paper result is
part of this local implementation.

Native semantics references: [Neo4j 5 relationship patterns](https://neo4j.com/docs/cypher-manual/5/patterns/reference/node-and-relationship-patterns/),
[relationship reuse with separate MATCH clauses](https://neo4j.com/docs/cypher-manual/4.0/syntax/patterns/),
and [SPARQL 1.1 basic graph patterns](https://www.w3.org/TR/sparql11-query/#BasicGraphPatterns).

## Acceptance results

The public `compile_directed_rows` API emits a `QueryArtifact`, while
`DirectedRowFragmentCompiler` creates the existing `CompiledBackendFragment`
and `RemoteQuery` node. The latter runs through the ordinary plugin registry,
scheduler and coordinator projection; it does not bypass accounting or turn a
backend error into empty success. Declared output columns must match the
compiler's traversal-position columns exactly. Answer projection belongs to a
separate explicit coordinator operation.

Primitive capability requirements, input-pattern hash, backend-profile hash,
directions and output columns are bound in each artifact. SPARQL additionally
binds the dataset-owned mapping identity and used expanded IRIs. Missing,
incompatible or unsafe mappings are refused; no entity IRI is guessed from a
model-generated identifier. These identities document compilation inputs, not
proof that a dataset has been loaded with the required representation.

The first independent-engine run exposed a real supplementary-Unicode defect:
JSON-style surrogate-pair escapes failed to match an emoji literal in SPARQL.
The new compiler preserves Unicode scalar characters and escapes quotes and
controls, rejects lone surrogates and unsafe identifiers/IRI expansions, and
does not change the old M9 literal emitter. A malformed NodeNotEquals also
exposed a validation-order issue: the stricter opt-in semantic checker now
checks reference kinds before the legacy checker dereferences them, returning
a typed rejection rather than AttributeError. The legacy checker itself is
unchanged.

The focused compiler/semantic/grounding/feedback/runtime gate passes **301
tests**. It includes emitted SPARQL executed by **RDFLib 7.1.4** against an
independent triple-walk oracle for every OUT/IN combination at lengths 1–4,
mixed labels, wildcard predicates, cycles, self-loops, repeated edges,
endpoint/middle conditions, explicit node inequalities, length predicates,
scalar filters, missing values and hostile-looking Unicode/literal inputs.
The scheduler integration executes actual emitted SPARQL; a separate failure
test verifies a failed backend is invoked once and remains a failure.

RDFLib is an optional **test-only** dependency (`test-sparql` extra); it is not
a production backend, fallback evaluator or new core dependency. Tests needing
it explicitly skip when it is absent. This validation used a temporary isolated
Python environment, not the user's CWRU environment. Full offline acceptance
passes **2479 tests, 36 skipped, in 617.48 seconds**. The new compiler tests
alone pass 119 tests with RDFLib; the base environment explicitly reports
66 passed and 53 skipped without it. Three existing offline examples,
formatting and `git diff --check` also pass. Skipped/live behavior is not
inferred to pass.

## Uploaded candidate compilation, not answer evaluation

A read-only check verified all 18 request/view bindings in the original
3796877 `query_states.jsonl`, SHA-256
`f207a5d4e3563e391274ebc0109ce2906a5ea2a007b27f4b362823c1bd887c18`.
Current canonical grounding and typed validation retain the same four
candidates as D193/D194. All four now compile with the opt-in Cypher profile:

| Question | Candidate | Directions | Native text SHA-256 |
|---|---|---|---|
| 2102933007000 | c1 | OUT | ce6b7993e6bcf6c5e108e96d0640bfbdb29559617cf29ba88bb4fa81516ee737 |
| 2102933007000 | c3 | OUT, IN, OUT | 9caf1465cf8b7a403b3a1544d189c87ee3c921d284a592b36226d775f848a68d |
| 3205285001000 | c2 | OUT, OUT | 531965445a5b24ed90ac57af2a978d66c492697d2e4c4625a8e5fab83a700913 |
| 3205285001000 | c3 | OUT, OUT, OUT | 05e928d04a23dc5bd4c7dc4fdc0638e705d700f2d1cd44352eec601c03df7930 |

This removes the previously identified **compilation** obstruction for the
OUT/IN/OUT candidate without rewriting it. It does not establish a loaded
Freebase property-graph mapping, actual Cypher execution, answer correctness or
new model accuracy. Zero model/backend calls were made, references were not
consulted, and the uploaded source bytes remained unchanged. No old metric or
capability record is overwritten or retrospectively promoted.

## Remaining acceptance and development

- Real Neo4j/Fuseki execution remains unverified for this new profile. Local
  Docker is not running; no service was started and no CWRU job was submitted.
  The independent RDFLib engine is not represented as Fuseki evidence.
- Native row bindings are not a portable path identity representation. RDF
  edge columns are predicates, and the Neo4j HTTP representation is not a
  cross-backend entity-identity contract. Dataset-owned IDs, mapping, answer
  projection/normalization and exact-answer tests are still required.
- Scalar-property compilation assumes functional, type-consistent values with
  finite numeric data. RDF literal language/datatype representation must be
  specified by the dataset adapter. Numeric Cypher guards require Neo4j 5.10+
  and are not a claim of support on an unverified older deployment.
- Undirected, alternation, recursive/optional/bounded expressions, non-ALL
  selectors, disjunction/negation and RDF edge reification remain explicit
  unsupported outcomes. This first directed profile does not complete the
  target GrailQA structural inventory or general semantic-DAG compilation.
- The existing no-backend GrailQA runner and all frozen scientific inputs stay
  unchanged. Its execution protocol cannot be expanded simply by importing
  this compiler. Finish the separate dataset-bound native correctness and
  answer gate, then connect the wider semantic program and physical plans.
- CPU catalog job 3796988 still has only the user's earlier running report;
  this work does not independently poll it or infer completion. New live
  output-contract/catalog measurements and full EQ1–EQ5 on both selected
  datasets remain required. No full150 or paper admission follows here.
