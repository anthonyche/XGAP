# GrailQA Paper Vertical Slice

## Result

M13-C completes a reproducible semantic and native-compilation vertical slice
for a restricted GrailQA train/dev fragment. The current recommendation is:

> **1. GrailQA is suitable for semantic-only paper evaluation.**

It is not yet suitable for claims based on real Freebase execution or rich
physical-plan alternatives.

## Pilot Bundle

`datasets/grailqa_pilot_v1/` contains 150 deterministically selected public
train/dev questions. Seed 1303 applies an 80/20 train/dev quota and seeded
round-robin sampling over `Q(u)`, path length, `A(u)` bucket, query function,
and first relation domain. Selection never reads XGAP prediction, execution,
or correctness outcomes.

| Dimension | Distribution |
|---|---|
| Split | train 120; dev 30 |
| Q / path length | 13/1: 83; 19/2: 56; 25/3: 11 |
| Function | none 140; numeric comparison 10 |
| A bucket at recommended epsilon | A=2..3: 27; A=4..8: 74; A>=9: 49 |
| First-relation domains | 61 |

The exact IDs and seed are in `pilot_ids.json`. The DatasetBundle content hash
is `87ae8633712a54e30dd96154201248bbf3abe1fde5bdf104f09a92c5a472bac4`.
Every non-manifest file has a byte count and SHA-256 entry in
`artifact_manifest.json`.

Gold answers, gold logical forms, reference interpretations, query slots, and
the evaluation entity catalog are evaluation-only. Runtime aliases and the
runtime entity catalog are deliberately empty because this sprint did not
identify and freeze a complete public, versioned Freebase alias catalog. The
inference manifest states `gold_exposed_to_inference=false`, and runtime
alignment tests enforce the boundary.

## Deterministic Pipeline

Three representative questions with `Q=13`, `Q=19`, and `Q=25` traverse the
actual implementation:

```text
evaluation-only controlled candidate
  -> frozen provided c_sem
  -> PathPatternQuery type checking and lowering
  -> M11 physical planning with an uncalibrated prior-only GP
  -> M9 Cypher and SPARQL compilation
```

All three lower, validate, produce one selected M11 plan, and compile for both
native targets. The persisted Top-1 accuracy, Candidate Recall, and Feasible
Coverage values are 1.0 only for this controlled three-case pipeline-integrity
smoke. They are explicitly not paper measurements.

The live Qwen boundary remains gated by `XGAP_RUN_LIVE_LLM=1` and
`DASHSCOPE_API_KEY`, and the existing M12-B prompt is unchanged. It was not run
because an inference-safe public alias/entity catalog has not been frozen.
Using evaluation gold anchors to make the smoke pass would violate the sprint
boundary.

## Mapping And Answers

`backend_mapping.yaml` is the only canonical-to-native mapping source. It maps
Freebase dotted IDs to Neo4j identifiers and Fuseki IRIs; neither compiler has
a GrailQA dataset branch. Mapping tests compile the same structured query for
both targets and verify that the SPARQL namespace comes from the artifact.

Answer normalization preserves Freebase MIDs as entity equivalence keys and
uses labels only as display metadata. Scalar answers retain their normalized
lexical value in the supported fragment. Results are deduplicated and sorted
by typed equivalence key when answer order is not semantic.

## Freebase Execution Feasibility

The outcome is **C: only semantic evaluation is currently practical**.

Google's historical [Freebase Data Dumps](https://developers.google.com/freebase)
page describes a public CC-BY RDF dump with about 1.9 billion triples, roughly
22 GiB compressed and 250 GiB uncompressed. The artifact has not been
downloaded, hashed, repaired, loaded, or performance-tested in XGAP.

The official GrailQA repository directs users to its
[Freebase setup](https://github.com/dki-lab/GrailQA), and the associated
[Freebase-Setup repository](https://github.com/dki-lab/Freebase-Setup) uses a
processed Virtuoso database. That setup documents at least 53 GiB disk and
recommends at least 100 GiB memory, and notes literal-format problems in the
official dump that require preprocessing for triple stores.

For Fuseki, a query-independent repaired N-Triples artifact followed by TDB
bulk loading appears technically plausible, but its data hash, conversion,
resource envelope, and result equivalence are not established. For Neo4j, a
deterministic streaming converter would need to preserve MIDs, CVTs, types,
relations, and typed literals; no such artifact exists in this repository.

No per-query subset was built because constructing execution data from pilot
gold forms or answers would leak evaluation evidence. `financial_risk` D0 was
not reused, no GrailQA D0 was created, and backend execution remains explicitly
blocked in `vertical_slice_results.json`.

## Physical Planning

Across all 150 pilot interpretations, current M11 all-local complete-plan
placement finds exactly one realization each: minimum, median, p90, and maximum
are all 1; fractions above one and above two are both 0. M9 separately compiles
each `PathPatternQuery` to two native languages, but this does not create a rich
M11 physical search space because the full lowered selector plans retain
`GroupBy` and `Projection` capabilities not claimed by the native profiles.

Therefore GrailQA in its present form cannot support a meaningful physical
planning RQ2 or regret claim. It can support semantic interpretation metrics
and deterministic lowering/native-compilation feasibility.

## Reproduction

```bash
PYTHONPATH=src python -m xgap.experiments.grailqa_v2 \
  --dataset-root <GrailQA_v1.0> \
  --ontology-root <GrailQA_ontology> \
  --ontology-revision bc15df916ca4101f773722151c90ba3f9eff9df5 \
  --output datasets/grailqa_audit_v2

PYTHONPATH=src python -m xgap.experiments.grailqa_pilot \
  --dataset-root <GrailQA_v1.0> \
  --ontology-root <GrailQA_ontology> \
  --audit-root datasets/grailqa_audit_v2 \
  --output datasets/grailqa_pilot_v1 \
  --size 150 --seed 1303
```

The next evidence step is a separately reviewed, query-independent Freebase
snapshot and loader freeze. Full sweeps, prompt tuning, model training, and
paper result claims remain outside M13-C.
