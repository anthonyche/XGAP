# GrailQA Query-Conditioned Local Freebase Catalog

## Motivation

The global M13-E3 Catalog-v2 build is scientifically clean but materializes a
SQLite/FTS index over the full Freebase entity space. Its source scan is linear,
while global row retention, random SQLite writes, FTS construction, and final
artifact size are costly on shared storage.

M13-E3B asks a narrower scientific question: does XGAP need a global entity
index, or is a bounded inference-time grounding context sufficient? It reuses
the exact frozen `CleverThis/freebase` Parquet source at revision
`dbb1931c2698295653effe9b980a02ab29f004e0` and does not modify or wait for the
independent global build.

## Fairness

For each question `u`, the local entity universe is defined as:

```text
normalized contiguous spans of text(u)
  -> exact normalized English Freebase name/alias matches
  -> existing lexical score, MID tie-break
  -> at most 50 MIDs
  -> public Freebase type enrichment
```

Construction accepts only the inference-side `question_id` and `text` fields.
Records containing gold, answer, logical-form, pattern-query, or reference
fields are rejected. Reference interpretations are not accepted by the build
function or build CLI. The audit is a separate phase and opens references only
after the gold-free retrieval rows have been persisted.

Each query has an independent candidate map. One physical source scan can batch
queries, but an entity matched for one question is not assigned to another.
The final SQLite database binds every allowlist to both `question_id` and the
SHA-256 of the original question text. Tests require batched and independent
selection to produce identical per-query results.

## Artifact

Two artifacts are defined independently:

| Workload | Questions | Artifact root |
|---|---:|---|
| `preflight18` | 18 | `$XGAP_GRAILQA_LOCAL_CATALOG_ROOT/preflight18` |
| `pilot150` | 150 | `$XGAP_GRAILQA_LOCAL_CATALOG_ROOT/pilot150` |

Pass 1 projects `subject`, `predicate`, `object`, `object_type`, and
`object_language`, and scans only `type.object.name` and
`common.topic.alias`. Only English literals with valid `m.*` or `g.*` MIDs are
eligible. Pass 2 uses the same projected columns, adds `type.object.type`, and
pushes down the frozen candidate MID union. Unrelated entities and type
memberships are discarded. No factual edges or k-hop subgraph are retained.

The retained subset reuses the Catalog-v2 entities, aliases, types, ontology
terms, relation metadata, FTS, and JSONL schema. Additive local tables and files
record questions, ranks, scores, matched labels, match type, and source shard.
The manifest records source/question hashes, frozen anchor policy, counts,
nominal source bytes scanned, wall time, peak RSS, SQLite size, Git commit, and
`gold_used_for_construction=false`.

For a manifest with `requires_query_entity_filter=true`, the persisted local
rank is also the downstream entity-retrieval contract. Retrieval verifies the
question ID and text hash, reads only that question's assignments, orders by
persisted rank and MID, preserves the persisted lexical score, and returns the
requested prefix. It does not pass those candidates through the global FTS
ranker. Catalogs without the query-local marker retain the original global FTS
behavior.

Intermediate SQLite writes occur under `$TMPDIR` or
`XGAP_LOCAL_CATALOG_STAGING_ROOT`. A validated copy is made beside the
persistent destination and atomically renamed into place. The global
`XGAP_FREEBASE_CATALOG_DIR` and `.catalog-v2.building` are explicitly rejected
as local outputs.

## CWRU Commands

The frozen E3A shards must already exist; these commands do not download a
second representation.

```bash
cd "$HOME/XGAP"
git pull

export XGAP_FREEBASE_RAW_DIR="$HOME/xgap-data/freebase/raw"
export XGAP_FREEBASE_PARQUET_ROOT="$XGAP_FREEBASE_RAW_DIR/hf-archival-parquet"
export XGAP_FREEBASE_SOURCE_MANIFEST="$XGAP_FREEBASE_RAW_DIR/source_manifest.json"
export XGAP_GRAILQA_LOCAL_CATALOG_ROOT="$HOME/xgap-data/freebase/grailqa-local-catalog-v1"
```

Build and audit the 18-query artifact first:

```bash
XGAP_LOCAL_CATALOG_WORKLOAD=preflight18 \
  sbatch --export=ALL scripts/slurm/build_grailqa_local_catalog.sbatch
```

After reviewing the 18-query result, build and audit the 150-query artifact:

```bash
XGAP_LOCAL_CATALOG_WORKLOAD=pilot150 \
  sbatch --export=ALL scripts/slurm/build_grailqa_local_catalog.sbatch
```

For an interactive allocation, the equivalent command is:

```bash
XGAP_LOCAL_CATALOG_WORKLOAD=preflight18 \
  bash scripts/server/build_grailqa_local_catalog.sh
```

After installing E3B.2, rerun only the offline audit over an existing artifact:

```bash
XGAP_LOCAL_CATALOG_WORKLOAD=preflight18 \
  bash scripts/server/build_grailqa_local_catalog.sh --audit-only
```

The Slurm equivalent is:

```bash
XGAP_LOCAL_CATALOG_WORKLOAD=preflight18 \
XGAP_LOCAL_CATALOG_AUDIT_ONLY=1 \
  sbatch --export=ALL scripts/slurm/build_grailqa_local_catalog.sbatch
```

Both audit-only paths reuse `catalog.sqlite3`; they do not verify, rebuild, or
rescan the Parquet source.

The Slurm job requests 8 CPUs, 48 GB memory, no GPU, and uses the job's
`$TMPDIR`. `sbatch` resource flags may override the committed defaults. It does
not start Qwen or vLLM.

## Reachability

Each workload root contains:

```text
manifest.json
catalog.sqlite3
catalog_coverage.json
retrieval_metrics.json
prompt_reachability.json
stage_failure_counts.json
entity_retrieval_before_after.json
relation_diagnostics.jsonl
type_diagnostics.jsonl
schema_ranking_before_after.json
relation_ranking_audit.jsonl
type_ranking_audit.jsonl
relation_diagnostics_v2.jsonl
type_diagnostics_v2.jsonl
endpoint_grounding_before_after.json
relation_endpoint_diagnostics.jsonl
audit_summary.json
retrieval.jsonl
reachability.jsonl
```

The audit reuses M13-E1 catalog, Recall@1/5/10/20, relation-slot,
all-required-relation, prompt-visible, and joint metrics. Its first-failure
taxonomy is:

1. `reference_not_in_local_catalog`
2. `reference_not_retrieved`
3. `reference_not_prompt_visible`

The unchanged engineering gate is Joint Prompt Reachability >= 0.20. The
result is recorded as `live_preflight_allowed`; no LLM job is submitted
automatically.

The real CWRU preflight18 build completed with 865 unique entities, 900
query-candidate assignments, approximately 45 minutes wall time, and an
approximately 14.4 MB SQLite database. Its first, pre-E3B.2 audit measured:

| Metric | Pre-E3B.2 |
|---|---:|
| EntityCatalogCoverage | 10/18 (55.6%) |
| Entity Recall@20 | 0/18 |
| Relation Recall@20 | 8/18 |
| Type Recall@20 | 6/18 |
| JointPromptReachability | 0/18 |

`entity_retrieval_before_after.json` preserves this prior metric snapshot. The
real E3B.2 rerun measured Entity Recall@1/5/10/20 of 3/7/8/8 over 18, entity
prompt coverage 7/18, and JointPromptReachability 1/18. Relation diagnostics
classified 0 ontology-universe misses, 10 retrieval misses, 6 prompt
truncations, and 2 reachable questions. Type diagnostics classified 0, 12, 2,
and 4 respectively. These engineering diagnostics establish schema ranking as
the next bottleneck; they are not paper accuracy results.

## M13-E3B.3 Schema Retrieval Diagnosis

The E3B.2 audit confirms that every required relation and type is in the frozen
ontology. Entity ranking was repaired and validated separately. E3B.3 therefore
changes only deterministic relation/type ranking and leaves the local entity
universe, persisted entity order, Top-50, prompt limit 4, gate 0.20, ontology,
and model path unchanged.

The pre-repair relation ranker already aggregated descriptors by term before
Top-k, so no relation alias-row truncation defect was found. Its ranking signal
was nevertheless a continuous token-overlap fraction plus substring bonus;
domain/range/reverse descriptors shared that score, and later slots had only a
fixed chain bonus. The first slot did not use the retained query-local entity
types. The pre-repair type path selected lexical Top-20 first and only then
merged relation-induced types, so provenance could not compete at the proper
pre-truncation boundary.

The frozen `m13e3b3-ontology-aware-schema-ranking-v1` contract is:

1. Aggregate canonical labels, public aliases, schema IDs, and public metadata
   descriptors by schema term, deduplicate, then rank terms and truncate.
2. Rank lexical evidence lexicographically as exact normalized multi-token
   phrase, complete informative-token coverage, contiguous partial phrase,
   informative partial overlap, generic single-token overlap, then zero overlap.
3. Use smoothed IDF derived only from the frozen relation/type descriptor
   vocabulary as a secondary tie-break. Persist its statistics hash.
4. Use the first four query-local entity candidates' public types as first-slot
   coherence. Propagate endpoint types through each prior slot's first four
   relations. Domain/range compatibility breaks lexical ties; when no slot
   direction exists it is evaluated bidirectionally and no direction is
   invented.
5. Aggregate type provenance from lexical ontology retrieval, entity-attached
   types, relation domain/range, and bounded ontology expansion before Top-k.
   Direct ontology provenance sits below exact phrase evidence and above
   weaker lexical evidence.
6. Resolve all remaining ties by ascending canonical schema ID. Ranking APIs
   accept no gold, reference, answer, LLM, or learned-model input.

The audit persists deployed retrieval before opening reference files. For each
question it then computes the complete trace through a provider that accepts
only the inference question ID/text; only after that trace exists does it read
the corresponding semantic requirements to select diagnostic terms and compute
Recall. Traces are processed one question at a time to bound memory. Existing
`relation_diagnostics.jsonl` and `type_diagnostics.jsonl` are retained when
present and their hashes are recorded. The five E3B.3 files contain complete
old/new score decomposition, required pre-truncation ranks, Top-20/Top-4
membership, beating candidates, provenance, stage counts, and a generic
failure taxonomy.

The real CWRU post-repair audit measured Relation Recall@1/5/10/20 of
5/11/12/13 over 18 and relation prompt coverage@4 of 10/18. Type
Recall@1/5/10/20 was 1/4/8/13 and explicit Type prompt coverage@4 remained
4/18. Relation stages became 0 ontology-universe misses, 5 retrieval misses, 3
prompt truncations, and 10 reachable; Type stages became 0, 5, 9, and 4.
JointPromptReachability remained 1/18, so the unchanged gate stayed closed.

## M13-E3B.4 Relation Endpoint Grounding Contract

The E3B.3 diagnostics showed a narrower contract mismatch: some selected
Top-4 relations already carried exact required endpoint types in their public
domain/range metadata, but the explicit Type Top-4 list remained the only class
visibility source used by runtime grounding and the offline gate.

E3B.4 adds no ranking signal and no prompt term. A shared deterministic helper
derives endpoint evidence only from the candidate's selected prompt-visible
relation realization. OUT maps domain to source and range to target; IN
reverses those roles; UNDIRECTED accepts either exact endpoint type for either
role. A fixed multi-hop path uses only the first hop for the outer source and
the last hop for the outer target. Alternation, optionality, and repetition do
not receive derived evidence. The candidate relation label, component ref,
hop slot, direction, endpoint role, and type ID remain auditable.

Offline reachability preserves `type` as the explicit Type-candidate metric and
adds `relation_endpoint_type` plus role-aware `effective_type`. `joint` and the
unchanged 0.20 gate use `effective_type`, matching runtime admissibility. The
first CWRU E3B.4 audit-only rerun will write
`endpoint_grounding_before_after.json` and
`relation_endpoint_diagnostics.jsonl`; no real improvement is claimed until
those artifacts are returned.

## Full-vs-Local Comparison

`python -m xgap.experiments.grailqa_local_catalog compare` writes
`full_vs_local_comparison.json`. Until the independent global job finishes,
every Full value is explicitly `null` with status `pending_global_build`.

| Metric | Full | Local |
|---|---:|---:|
| artifact size | pending | approximately 14.4 MB |
| construction wall time | pending | approximately 45 minutes |
| unique entities | pending | 865 |
| EntityCatalogCoverage | pending | 10/18 |
| Entity Recall@20 | pending | 8/18 (44.4%) |
| JointPromptReachability | pending | 1/18 (5.56%), post-E3B.3 |

The first run revealed the generic local/global ordering defect repaired by
E3B.2. It did not authorize score tuning. Embeddings, NER, query-specific
aliases, gold-derived candidates, backend snapshots, relation/type retrieval
changes, and Qwen execution remain outside M13-E3B.2. E3B.3 adds only the
generic, gold-blind schema-ranking repair described above. E3B.4 adds only the
shared role-aware endpoint visibility contract; its real metric remains
pending the audit-only rerun.
