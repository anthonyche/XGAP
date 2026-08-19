# GrailQA Freebase Catalog-v2 Reachability

## Status

**IMPLEMENTATION READY; CWRU MEASUREMENT PENDING.**

The offline builder, integrity checks, frozen M13-E1 retrieval, all-supported
catalog audit, frozen-150 prompt audit, and CPU Slurm workflow are implemented.
The official Freebase dump has not been processed in this local environment,
so this report intentionally contains no fabricated catalog or recall values.

## Artifact Boundary

- **Freebase RDF dump:** Google's final public, gzip-compressed N-Triples
  snapshot. It is raw external KG data and is never committed.
- **Freebase inference catalog:** query-independent MID/name/English-alias/type
  metadata in SQLite/FTS5. It is used only for inference-time grounding.
- **GrailQA ontology:** the frozen official processed schema remains the source
  for classes, relations, hierarchy, domain/range, reverse properties, and
  semantic reasoning.
- **Freebase backend snapshot:** not built by M13-E3.

Google documents the historical dump as approximately 1.9 billion triples,
22 GB gzip and 250 GB uncompressed, N-Triples UTF-8, under CC-BY. The builder
reads gzip directly and indexes only English `type.object.name` and
`common.topic.alias` literals plus `type.object.type` memberships.

## Catalog

| Measurement | Result |
|---|---:|
| Entities | pending CWRU build |
| Canonical names | pending CWRU build |
| English aliases | pending CWRU build |
| Type memberships | pending CWRU build |
| GrailQA relations | pending CWRU build |
| GrailQA types | pending CWRU build |
| SQLite size | pending CWRU build |

## Catalog Coverage

Coverage is evaluation-only and is measured separately over all 35,439
supported train/dev questions and the frozen 150-query pilot.

| Metric | All 35,439 | Frozen 150 |
|---|---:|---:|
| Entity | pending | pending |
| Relation | pending | pending |
| Type | pending | pending |
| Joint | pending | pending |

## Retrieval Recall@k

This first audit runs the M13-E1 retriever unchanged. Gold annotations are
joined only after retrieval artifacts have been persisted.

| Metric | @1 | @5 | @10 | @20 |
|---|---:|---:|---:|---:|
| Entity | pending | pending | pending | pending |
| At least one required relation | pending | pending | pending | pending |
| All required relations | pending | pending | pending | pending |
| Type | pending | pending | pending | pending |

Per-hop slot recall is emitted in `retrieval_metrics.json`.

## Prompt Reachability

`PromptReachability@k` applies the frozen M13-E1 bound of at most four
candidates per slot/entity pool, so retrieval beyond that bound can be reported
as retrieved-but-excluded. The separately reported deployed metric uses the
actual bound of four.

| Metric | @1 | @5 | @10 | @20 |
|---|---:|---:|---:|---:|
| Entity prompt coverage | pending | pending | pending | pending |
| Relation prompt coverage | pending | pending | pending | pending |
| Type prompt coverage | pending | pending | pending | pending |
| Joint prompt reachability | pending | pending | pending | pending |

## Stage Failure

Every unreachable question is assigned exactly one first failure:

1. `reference_not_in_catalog`
2. `reference_not_retrieved`
3. `reference_not_prompt_visible`

Counts and percentages are pending the CWRU audit. No LLM failure class is
valid in this milestone.

## Complexity And Path Analysis

The compact outputs stratify catalog/retrieval/prompt metrics by `Q=13`,
`Q=19`, `Q=25` and path lengths 1, 2, and 3. Values are pending CWRU.

## Gate

- Engineering threshold: deployed joint prompt reachability `>= 0.20`.
- `live_preflight_allowed`: pending.
- The threshold is a cost-control safeguard, not a paper metric.
- Even a GO result does not run Qwen; it only authorizes the separately scoped
  18-query M13-E2 preflight.

## Scope

M13-E3 does not change retrieval ranking, prompt construction, `c_sem`, Nash
ranking, PathPatternQuery semantics, path algebra, M11, GP estimation,
compilers, backend execution, or model/provider code. It does not load
Freebase into Neo4j/Fuseki and does not run Qwen, DashScope, or vLLM.
