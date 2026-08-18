# GrailQA Artifact Audit V2

## Scope

This report records the M13-C rerun over GrailQA v1.0 after the minimal
`NodeNotEquals` condition extension and the experiment-only fixed-path
converter upgrade. It preserves the M13-A artifacts and writes all new output
under `datasets/grailqa_audit_v2/`. The audit is a train/dev gold-visible
evaluation audit, not an inference procedure and not a completed backend run.

## Provenance

The audit classified all 64,331 public questions: 44,337 train, 6,763 dev, and
13,231 public test. Public test has no gold logical forms and is therefore
always recorded as `missing_gold_logical_form`. Dataset and ontology source
hashes, including the GrailQA ontology revision
`bc15df916ca4101f773722151c90ba3f9eff9df5`, are frozen in
`audit_summary.json`.

## Coverage

| Measure | M13-A | M13-C v2 | Change |
|---|---:|---:|---:|
| Supported train/dev | 23,156 | 35,439 | +12,283 |
| Gold-available support | 45.315% | 69.352% | +24.037 points |
| All-public support | 35.995% | 55.089% | +19.094 points |
| Unsupported train/dev | 27,944 | 15,661 | -12,283 |

The Phase A estimate was 35,454. The measured result is 15 lower because 15
questions reference `music.album.supporting_tours`, which occurs on a malformed
concatenated line in the official `fb_roles` resource and cannot be parsed as a
canonical public relation. The converter rejects it rather than repairing or
inventing a mapping.

Supported query types are 34,973 unaggregated path questions and 466 numeric
comparisons (`<`: 139, `<=`: 126, `>`: 35, `>=`: 166). `COUNT`, `ARGMAX`, and
`ARGMIN` remain unsupported.

## Unsupported Taxonomy

| First failure reason | Questions |
|---|---:|
| Missing public-test gold logical form | 13,231 |
| Unsupported path semantics | 4,813 |
| Missing entity mapping / unsupported anchor shape | 3,089 |
| Unsupported ordering or superlative | 3,146 |
| Unsupported aggregation | 2,744 |
| Unsupported comparison | 1,633 |
| Missing or unrealizable relation mapping | 222 |
| Missing ontology term | 14 |

These are first-failure categories and must not be interpreted as independent
or additive latent coverage opportunities.

## Mapping

Canonical terms remain Freebase dotted identifiers. The v2 mapping contains
10,656 class terms, 13,747 relation terms, and 5,531 property terms. Neo4j uses
the canonical term as its native label/type/property identifier. Fuseki uses
the mapped `http://rdf.freebase.com/ns/` IRI. The DatasetBundle mapping, not the
SPARQL compiler, owns that namespace.

Only public GrailQA ontology resources and declared reverse properties are
used. Endpoint orientation may change to preserve an available public relation,
but no inverse relation is synthesized. Per-question gold IDs are used only to
measure anchor coverage and build evaluation-only reference records; they are
not runtime grounding input.

## Structural Diversity

`Q(u)` is recomputed from each serialized canonical plan as
`|Omega_u^gold| + |D_u^gold|`.

| Statistic | M13-A | M13-C v2 |
|---|---:|---:|
| Distinct Q values | 1 | 3 |
| Mean | 13 | 14.680 |
| Median | 13 | 13 |
| p90 | 13 | 19 |
| Maximum | 13 | 25 |

| Path length / Q | Count |
|---|---:|
| 1 / 13 | 26,002 |
| 2 / 19 | 8,952 |
| 3 / 25 | 485 |

The complete operator distribution is: `Edges` 45,361, `Join` 9,922,
`Selection` 151,678, `GroupBy` 35,439, and `Projection` 35,439. Thus M13-C
improves both coverage and fixed-path structural diversity without adding a
logical operator.

## Ontology Normalization

The original hierarchy has 18,235 edges. Deterministic Tarjan SCC
condensation chooses the lexicographically smallest term as each component
representative, removes 16 self edges, and emits a 10,648-component DAG with
18,142 edges. Ten components are cyclic and contain 18 terms. Internal SCC
edges are represented by the persisted equivalence map; no hierarchy edge is
silently discarded and no edge is invented.

The original ontology hash is
`65d6a618b890fe96998ef7d9e015732bb045be4b101863a4b90014525d5a5e58`.
The normalized ontology hash used by semantic-deviation analysis is
`8bd4f19503d3a61a89831da1d040afea93fae1f64446e0ffb206b510bb69c10b`.

## Reference Ambiguity

`A(u)` counts distinct, evaluation-only reference interpretations satisfying
the unchanged frozen `c_sem <= epsilon_amb` rule. Alternatives consist of the
exact interpretation plus deterministic single-slot direct parent/child
substitutions from the normalized ontology, capped at eight alternatives per
slot and deduplicated by canonical structured interpretation. It is not the
number of LLM candidates and is never exposed to inference.

| epsilon | A=1 | A=2 | A=3 | A>=4 | Mean | Median | Max |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 100.000% | 0% | 0% | 0% | 1.000 | 1 | 1 |
| 0.05 | 31.801% | 9.490% | 6.442% | 52.267% | 5.160 | 4 | 25 |
| 0.10 | 0.065% | 0% | 12.675% | 87.260% | 7.712 | 7 | 25 |
| 0.25 | 0.065% | 0% | 12.675% | 87.260% | 7.712 | 7 | 25 |

`epsilon_amb=0.10` is recommended for pilot stratification because it retains
the fixed M12 semantic scale and yields a non-degenerate bounded reference
space. It is not frozen as a final paper hyperparameter. The equality of the
0.10 and 0.25 rows is a property of the bounded direct-neighbor candidate
space, not a tuned outcome.

## Boundary

M13-C does not support scalar count output, superlative property semantics,
focus-only property queries, branching or disconnected graph patterns,
multiple anchors, arbitrary SPARQL, hidden test gold, or end-to-end Freebase
execution. These remain explicit unsupported records rather than empty
results or approximations.
