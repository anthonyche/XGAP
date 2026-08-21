# GrailQA Semantic Preflight v2 Runbook

## Purpose

This runbook prepares one guarded 18-query live correctness preflight. It does
not authorize another 150-query run. The frozen spec hash is
`b02e67acd1f7b8f79d2cb7f3d48df7e5b2beb6c9e6624d1b1f5740921e3f2f35`.

## 1. Build Catalog And Offline Reachability

Use large server storage; the default follows `$HOME/xgap-data`:

```bash
cd /home/chl/XGAP
export XGAP_FREEBASE_SOURCE_MODE=hf_archival_parquet
bash scripts/server/smoke_freebase_archival_parquet.sh
bash scripts/server/build_grailqa_catalog_v2.sh --download
```

To reuse a pre-downloaded frozen archival shard tree:

```bash
export XGAP_FREEBASE_SOURCE_MODE=hf_archival_parquet
export XGAP_FREEBASE_RAW_DIR=/data/chl/xgap-artifacts/freebase-m13e3a/raw
export XGAP_FREEBASE_PARQUET_ROOT="$XGAP_FREEBASE_RAW_DIR/hf-archival-parquet"
export XGAP_FREEBASE_SOURCE_MANIFEST="$XGAP_FREEBASE_RAW_DIR/source_manifest.json"
bash scripts/server/verify_freebase_archival_parquet.sh
bash scripts/server/build_grailqa_catalog_v2.sh
```

The command builds and hashes catalog v2, audits catalog coverage over all
35,439 supported train/dev questions, then builds the full frozen 150-query
retrieval/reachability bundle. Exit 2 means the scientific gate failed; do not
run Qwen.

For the completed M13-E3B query-local `preflight18` artifact, E3B.2 requires
only a post-hoc audit. It must not rescan Freebase:

```bash
cd "$HOME/XGAP"
XGAP_LOCAL_CATALOG_WORKLOAD=preflight18 \
XGAP_LOCAL_CATALOG_AUDIT_ONLY=1 \
  sbatch --export=ALL scripts/slurm/build_grailqa_local_catalog.sbatch
```

Inspect `entity_retrieval_before_after.json`, `relation_diagnostics.jsonl`,
`type_diagnostics.jsonl`, and `prompt_reachability.json` under the existing
local artifact root. This command uses no GPU, Qwen, or provider credential.

## 2. Check Readiness

For CWRU with the completed query-local E3B.4 artifact:

```bash
cd "$HOME/XGAP"
bash scripts/server/check_cwru_grailqa_preflight_ready.sh
```

This selects `query_local_e3b4`, consumes the artifact's native
`audit_summary.json`, and validates the exact 18-query/hash/prompt-bound/
endpoint-contract tuple. It does not require vLLM to be running.

The following legacy command applies only to the separate query-independent
Catalog-v2 profile:

```bash
export DASHSCOPE_API_KEY='<server DashScope key>'
export XGAP_GRAILQA_CATALOG_V2="$HOME/xgap-data/grailqa-inference-catalog-v2"
export XGAP_GRAILQA_REACHABILITY_V2="$HOME/xgap-data/grailqa-reachability-v2"
bash scripts/check_grailqa_semantic_preflight_v2_ready.sh
```

Readiness prints catalog coverage, retrieval coverage, deployed prompt
reachability, and the frozen 0.20 joint-reachability safeguard. The threshold
is an engineering guard fixed before v2 model results, not a paper metric.

## 3. Run Exactly 18 Queries

On CWRU, only after the query-local readiness command passes:

```bash
JOB_ID=$(sbatch --parsable --export=ALL \
  scripts/slurm/run_grailqa_semantic_preflight_v2.sbatch)
echo "$JOB_ID"
```

For the separate remote-provider profile, the existing wrapper remains:

```bash
bash scripts/run_grailqa_semantic_preflight_v2.sh
```

The frozen sample contains Q/path-length counts 10/7/1 for 13/19/25 and
1/2/3, spans 17 first-relation domains, and contains different old-baseline
component-reachability levels. It was not selected by model performance.

## Success Evidence

The output records catalog availability, PromptReachability, provider and
structured-valid rates, Candidate Recall, component accuracy, full normalized
interpretation accuracy, `c_sem` distribution, Feasible Coverage, and the
stage-aware failure taxonomy. The query-local CWRU condition also records a
`jointly_reachable_subset` for the five prompt-reachable questions while
preserving all-18 metrics. No backend execution is performed. A future
150-query run remains disallowed until these diagnostics are interpretable.
