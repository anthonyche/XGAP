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

Real local entity counts, artifact sizes, build times, coverage, recall, prompt
reachability, and GO/NO-GO status are pending the CWRU runs. No local fixture
number is a paper result.

## Full-vs-Local Comparison

`python -m xgap.experiments.grailqa_local_catalog compare` writes
`full_vs_local_comparison.json`. Until the independent global job finishes,
every Full value is explicitly `null` with status `pending_global_build`.

| Metric | Full | Local |
|---|---:|---:|
| artifact size | pending | pending CWRU |
| construction wall time | pending | pending CWRU |
| unique entities | pending | pending CWRU |
| EntityCatalogCoverage | pending | pending CWRU |
| Entity Recall@20 | pending | pending CWRU |
| JointPromptReachability | pending | pending CWRU |

No retrieval policy should be changed after inspecting the first results unless
the run reveals a generic correctness defect. Embeddings, NER, query-specific
aliases, gold-derived candidates, backend snapshots, and Qwen execution are
outside M13-E3B.
