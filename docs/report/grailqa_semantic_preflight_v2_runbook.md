# GrailQA Semantic Preflight v2 Runbook

## Purpose

This runbook prepares one guarded 18-query live correctness preflight. It does
not authorize another 150-query run. The frozen spec hash is
`b02e67acd1f7b8f79d2cb7f3d48df7e5b2beb6c9e6624d1b1f5740921e3f2f35`.

## 1. Build Catalog And Offline Reachability

Use large server storage; the default follows `$HOME/xgap-data`:

```bash
cd /home/chl/XGAP
bash scripts/server/build_grailqa_catalog_v2.sh --download
```

To reuse a pre-downloaded dump:

```bash
export XGAP_FREEBASE_RDF=/data/chl/xgap-artifacts/freebase-m13e1-v2/freebase-rdf-latest.gz
bash scripts/server/build_grailqa_catalog_v2.sh
```

The command builds and hashes catalog v2, audits catalog coverage over all
35,439 supported train/dev questions, then builds the full frozen 150-query
retrieval/reachability bundle. Exit 2 means the scientific gate failed; do not
run Qwen.

## 2. Check Readiness

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

Only after readiness passes:

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
stage-aware failure taxonomy. No backend execution is performed. A future
150-query run remains disallowed until these diagnostics are interpretable.

