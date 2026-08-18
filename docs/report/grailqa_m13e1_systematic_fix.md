# M13-E1 Systematic Fix

## Implemented Offline Boundaries

- Reusable catalog/retrieval/prompt reachability with catalog, retrieval, and
  truncation decomposition, joint coverage, Q/path strata, and a fail-closed
  engineering gate.
- A streaming query-independent catalog-v2 builder over the official Google
  Freebase RDF dump using `type.object.name`, `common.topic.alias`, and
  `type.object.type`; no question/gold input is accepted.
- Deterministic exact/normalized alias and SQLite FTS5/BM25 entity retrieval.
- Relation descriptors from tokenized IDs, public names/aliases,
  domain/range, and reverse metadata; bounded 3-hop slot pools and bounded
  domain/range type expansion.
- A generic fixed-path canonical profile, typed condition schema,
  component-wise equivalence, stage-aware failure attribution, and `c_sem`
  distribution audit.
- An outcome-independent 18-query preflight and a live runner guarded by the
  offline reachability result.

## Public Source And Current Blocker

The selected comprehensive source is the final public Freebase RDF dump:
`https://storage.googleapis.com/freebase-public/rdf/freebase-rdf-latest.gz`.
Google documents approximately 1.9 billion triples, 22 GB compressed and 250
GB uncompressed, under Freebase's CC-BY terms. The official GrailQA processed
ontology remains the source for the supported relation/type universe,
hierarchy, domain/range, and reverse-property contract.

The dump is not present locally. Therefore the repository truthfully records
catalog v2 and reachability v2 as `blocked`; entity/alias counts, all-35,439
catalog coverage, repaired Recall@k, and new joint prompt reachability are not
claimed. The server builder hashes the downloaded source and all constructed
artifacts before changing that state. GrailQA reference annotations are never
used as a catalog fallback.

## Frozen Baseline

The M13-D diagnosis is reproduced exactly: catalog entity availability
12/150; retrieval Top-20 entity/relation/type 10/47/67; deployed prompt Top-4
9/22/38; joint 0/150. See the reachability postmortem and compact baseline
artifact.

## Post-Hoc Frozen-Response Audit

The server response files are not local. After copying the immutable run, use:

```bash
PYTHONPATH=src python -m xgap.experiments.interpretation_contract posthoc \
  --source-run /path/to/m13d-grailqa-semantic-pilot-v1 \
  --pilot-root datasets/grailqa_pilot_v1 \
  --reachability datasets/grailqa_m13d_reachability_baseline/reachability.jsonl \
  --output runs/m13d-posthoc-contract-audit
```

The command writes separate component and normalized diagnostic metrics. It
does not replace the frozen Candidate Recall 0 result.

## Ambiguity

Recommendation C is preserved. Current `A(u)` measures a bounded ontology
neighborhood around reference terms rather than independently validated,
question-conditioned interpretation multiplicity. No model result was used
to revisit that decision.

## Scope

No PathPatternQuery construct, logical operator, compiler, backend execution,
M11 search, GP, `c_sem`, KQA Pro path, few-shot prompt, model, or tuning policy
changed. M13-D artifacts and historical reports remain immutable.
