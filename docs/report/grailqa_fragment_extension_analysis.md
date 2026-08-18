# GrailQA Fragment Extension Analysis

## Scope and evidence

This is the required M13-C pre-extension analysis. It was completed before
changing production semantics. The analysis uses the public GrailQA v1.0
train/dev graph queries and S-expressions, the public Freebase roles/types and
reverse-property files bundled by the GrailQA project, the frozen M13-A audit,
and the current XGAP M0-M13-B implementation.

The M13-A audit contains 64,331 public questions. Gold logical forms are
available for 51,100 train/dev questions; the 13,231 public-test questions are
retained in coverage denominators but are not inspected or inferred. M13-A
supports 23,156 train/dev questions (45.315% of gold-visible questions and
35.995% of all public questions), all with structural complexity `Q=13`.

The counts below use the M13-A first-failure taxonomy. They are disjoint as
first failures, but prospective feature gains can overlap after a previous
failure is removed. Incremental estimates therefore must not be added unless
the selected converter is rerun and each question is counted once.

## Candidate extensions

| Category | M13-A first-failure count | First failure layer | Existing semantic support | Estimated incremental coverage | Implementation cost | Paper relevance |
|---|---:|---|---|---:|---|---|
| Selected path semantics | 12,671 | GrailQA-to-`PathPatternQuery` conversion; fixed multi-hop paths need pairwise node-identity inequality | `Seq`, positional `NodeRef`, `Join`, and `Selection` already cover fixed paths; node identity inequality is absent | 9,197 simple multi-hop questions | Medium | High: directly exercises deterministic path/GPC lowering |
| Ordering/superlatives | 3,146 | Interpretation/property-order semantics | `OrderBy` orders existing path/solution records; it does not encode GrailQA `ARGMAX`/`ARGMIN` property extrema and tie behavior | 0 selected | High | Medium |
| Aggregation | 2,744 | Interpretation result model and output kind | `GroupBy` partitions path-derived records; it is not scalar `COUNT`, and the current public result remains `PathSet` | 0 selected | High | Medium |
| Comparison | 2,391 | Mostly interpretation conversion; 1,335 cases are focus-only property comparisons | Finite numeric non-bool `PropertyLessThan`, `PropertyLessThanOrEqual`, `PropertyGreaterThan`, and `PropertyGreaterThanOrEqual` already lower through `Selection` and compile | 466 path-attached numeric comparisons | Low to medium | High: validates existing scalar-condition semantics without adding an operator |
| Entity mapping | 4,343 | Interpretation shape and grounding policy | Exact identifiers can be represented, but most failures have zero/multiple entity anchors, literal constraints, or non-path topology; no public alias lexicon justifies guessing | 0 selected | High | High, but leakage-sensitive |
| Relation mapping | 2,635 | M13-A converter requires an inverse predicate even when reversing the physical path would preserve the public edge direction | Direct edge labels and declared reverse-property metadata already exist | 2,635 one-hop questions | Low | High: removes a converter artifact without changing semantics |

Fourteen additional questions fail on a missing ontology term. They remain
unsupported unless the term is present in a public, versioned source.

## Structural findings

Among 42,819 non-aggregate/non-superlative train/dev graph queries, 42,444 are
undirected simple paths and 375 are branching or otherwise non-path. A
conservative candidate is accepted only when it has exactly one entity anchor,
one class-valued question node, both at path endpoints, no literal node, known
ontology classes, and a realizable sequence of public direct or declared
reverse predicates.

Under those conditions, 34,988 non-comparison questions are representable:

| Fixed path length | Questions |
|---:|---:|
| 1 | 25,791 |
| 2 | 8,723 |
| 3 | 474 |

Choosing either endpoint as the physical start, while preserving answer-focus
metadata, avoids unsupported synthetic inverses. The chosen orientation needs
zero inverse edges for 30,553 questions, one for 4,429, and two for 6. It
recovers all 2,635 M13-A relation-mapping failures and 9,197 simple multi-hop
path failures. Missing or undeclared inverse relations still fail explicitly.

The GrailQA graph-query encoding applies all-pairs inequality filters between
distinct query nodes. XGAP can already refer to fixed path positions through
`NodeRef`, but it cannot state that two positions denote different graph-node
identities. Property inequality is not equivalent. The narrow semantic gap is
therefore a generic binary node-identity condition:

```text
NodeNotEquals(left: NodeRef, right: NodeRef)
```

It requires no new logical operator. Type checking validates both positions,
lowering emits the existing `Selection`, reference evaluation compares node
identity, and native compilers emit the corresponding Cypher/SPARQL identity
predicate.

## Comparison subset

The current condition vocabulary already supports finite numeric comparisons.
M13-C can therefore admit 466 questions whose graph query contains exactly one
numeric literal leaf on a scalar property edge and whose remaining nonempty
graph is an accepted entity-to-answer simple path. The distribution is:

| Comparison | Questions |
|---|---:|
| `<` | 139 |
| `<=` | 126 |
| `>` | 35 |
| `>=` | 166 |

The remaining path has length one for 226 questions, two for 229, and three for
11. The scalar edge becomes an existing property condition on the appropriate
path-node position. Typed literal parsing must reject bools, non-finite values,
unknown datatypes, and unsupported units explicitly.

The other comparison questions are not silently approximated: 1,335 are
focus-only property queries, 266 use nonnumeric/date values, 215 do not have the
required anchor shape, 77 are non-path after removing the scalar edge, and 32
have multiple literal constraints.

## Selected M13-C fragment

M13-C selects exactly these changes:

1. Add `NodeNotEquals` as a generic scalar condition, with complete type
   checking, deterministic `Selection` lowering, validation, evaluation,
   feature inference, and Cypher/SPARQL compilation.
2. Extend the GrailQA reference converter to accepted fixed paths of length
   one through three, orienting the path only through public direct or declared
   reverse-property mappings and retaining explicit answer-focus metadata.
3. Reuse the existing numeric property comparison conditions for the 466
   accepted path-attached comparison questions.
4. Normalize ontology cycles through an explicit deterministic SCC
   condensation artifact before semantic-distance evaluation.

No new logical operator is justified. The selected fragment is expected to
support 35,454 gold-visible train/dev questions, an increase of 12,298 over
M13-A. This is 69.382% of gold-visible train/dev and 55.112% of the complete
public question inventory. These are pre-rerun estimates, not final audit
results.

For the estimated supported set, the structural-complexity distribution is
`Q=13` for 26,017 questions, `Q=19` for 8,952, and `Q=25` for 485 (mean 14.679,
median 13, p90 19, maximum 25). The M13-C v2 audit must recompute these values
from serialized plans rather than copying the estimates.

## Explicitly rejected extensions

- Scalar `COUNT` is rejected because the current `PathPatternQuery`, output
  kinds, and `GroupBy` semantics do not define a scalar cardinality result.
- `ARGMAX` and `ARGMIN` are rejected because property extrema, ties, and
  backend compilation are not represented by the current selector `OrderBy`.
- Focus-only property comparisons are rejected because they would require a
  new interpretation/result representation and backend property-access model.
- Branching patterns, arbitrary conjunctive matching, multiple anchors, and
  disconnected graph queries remain outside the path-centric core.
- Missing relation inverses are never invented. Only the versioned public
  reverse-property source may authorize an inverse mapping.
- Public-test gold forms, entities, and answers are never reconstructed or
  exposed to inference.
- KQA Pro qualifiers, arbitrary SPARQL, semantic-deviation redesign, search
  objective changes, model training, and prompt tuning are outside M13-C.

## Implementation consequence

The production change is deliberately small: one condition type and its
existing-pipeline integrations. All GrailQA-specific topology selection,
mapping, comparison extraction, normalization, pilot sampling, and reporting
remain in experiment/dataset modules. Unsupported constructs retain explicit,
auditable failure reasons.
