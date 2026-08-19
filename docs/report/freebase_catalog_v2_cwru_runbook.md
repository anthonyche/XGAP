# Freebase Catalog-v2 CWRU Runbook

## Scope And Storage

This is an offline CPU workflow. It does not start Qwen, vLLM, Neo4j, or
Fuseki. It downloads Google's final public Freebase RDF dump, streams the gzip
into the existing M13-E1 SQLite/FTS5 builder, validates the catalog, and audits
the frozen GrailQA workloads.

The raw dump is approximately 22 GB compressed and 250 GB uncompressed, but
the workflow never writes a decompressed copy. Use persistent shared storage,
not `/tmp/job.*` or `/scratch/pioneer/jobs/job.*`. The defaults below use
`$HOME/xgap-data`; replace them with a persistent project filesystem when home
quota is insufficient.

## 1. Synchronize Git

From CWRU OnDemand or a login-node shell:

```bash
cd "$HOME/XGAP"
git fetch origin
git pull --ff-only
git log -1 --oneline
git status --short
```

Record the HEAD and require an empty status before the paper build.

Verify that the previously frozen M13-D GrailQA artifacts are installed. They
contain the official train/dev projection and 150-query pilot but are excluded
from Git because of size:

```bash
bash scripts/server/fetch_grailqa_m13d_artifacts.sh --verify-only
test -s datasets/grailqa_audit_v2/supported_questions.jsonl
test -s datasets/grailqa_pilot_v1/inference_questions.jsonl
test -s datasets/grailqa_pilot_v1/reference_interpretations.jsonl
test -s datasets/grailqa_pilot_v1/workload_stats.jsonl
```

If verification reports them missing, install the frozen M13-D source cache
with `scripts/server/fetch_grailqa_m13d_artifacts.sh` before downloading
Freebase. M13-E3 never reconstructs these evaluation artifacts from catalog
contents.

## 2. Configure Persistent Paths

```bash
export XGAP_FREEBASE_RAW_DIR="$HOME/xgap-data/freebase/raw"
export XGAP_FREEBASE_CATALOG_DIR="$HOME/xgap-data/freebase/catalog-v2"
export XGAP_GRAILQA_CATALOG_V2="$XGAP_FREEBASE_CATALOG_DIR"
export XGAP_GRAILQA_REACHABILITY_V2="$HOME/xgap-data/freebase/grailqa-reachability-v2"

mkdir -p "$XGAP_FREEBASE_RAW_DIR" \
  "$XGAP_FREEBASE_CATALOG_DIR" \
  "$XGAP_GRAILQA_REACHABILITY_V2"
df -h "$XGAP_FREEBASE_RAW_DIR"
```

Export the same values before every later command or place them in a private
shell environment file. No credential is required.

## 3. Download The Raw Dump

```bash
cd "$HOME/XGAP"
bash scripts/server/download_freebase_rdf.sh
```

The script downloads only the official URL
`https://storage.googleapis.com/freebase-public/rdf/freebase-rdf-latest.gz`.
It resumes a `.part` file, atomically renames a successful transfer, and writes
`source_manifest.json` with retrieval time, HTTP metadata, byte size, and
SHA-256. It refuses to replace a final file whose existing manifest disagrees.

## 4. Verify The Raw Artifact

```bash
bash scripts/server/verify_freebase_rdf.sh
cat "$XGAP_FREEBASE_RAW_DIR/source_manifest.json"
```

Verification recomputes SHA-256 and size, then runs a streaming `gzip --test`.
This can take time but writes no decompressed file. A mismatch is fatal.

## 5. Submit The CPU Build

```bash
JOB_ID=$(sbatch --parsable --export=ALL \
  scripts/slurm/build_freebase_catalog_v2.sbatch)
echo "$JOB_ID"
```

The default request is 16 CPU cores, 128 GB memory, and 48 hours with no GPU.
Override scheduler resources without editing the repository when needed:

```bash
JOB_ID=$(sbatch --parsable --export=ALL \
  --cpus-per-task=24 --mem=192G --time=3-00:00:00 \
  scripts/slurm/build_freebase_catalog_v2.sbatch)
```

The job verifies the source, safely builds and publishes the catalog, validates
hashes/SQLite/indexes/schema membership, runs all-35,439 catalog coverage and
the frozen-150 M13-E1 retriever, then writes the GO/NO-GO summary. A failed
builder retry reuses the raw download. A complete catalog built from identical
inputs is verified and reused; `--force` is intentionally manual.

## 6. Monitor The Job

```bash
squeue -j "$JOB_ID"
scontrol show job "$JOB_ID"
tail -f "slurm-freebase-catalog-v2-${JOB_ID}.out"
```

The log begins with Git commit, hostname, paths, and allocated CPU count.

## 7. Inspect Catalog And Reachability

```bash
cat "$XGAP_FREEBASE_CATALOG_DIR/manifest.json"
cat "$XGAP_FREEBASE_CATALOG_DIR/integrity_report.json"
cat "$XGAP_GRAILQA_REACHABILITY_V2/audit_summary.json"
cat "$XGAP_GRAILQA_REACHABILITY_V2/catalog_coverage.json"
cat "$XGAP_GRAILQA_REACHABILITY_V2/retrieval_metrics.json"
cat "$XGAP_GRAILQA_REACHABILITY_V2/prompt_reachability.json"
cat "$XGAP_GRAILQA_REACHABILITY_V2/stage_failure_counts.json"
```

Success means catalog and audit status are `complete`, integrity status is
`ok`, both frozen workload counts are exact, and
`live_preflight_allowed` is explicitly `true` or `false`. A false gate is a
valid scientific NO-GO result, not catalog corruption. No LLM is called.

## 8. Independent Re-runs

The four stages can be rerun separately:

```bash
bash scripts/server/download_freebase_rdf.sh
bash scripts/server/verify_freebase_rdf.sh
bash scripts/server/build_freebase_catalog_v2.sh
bash scripts/server/audit_grailqa_reachability_v2.sh
```

The audit command exits 2 when the engineering gate is NO-GO. It still writes
a complete offline report. Do not proceed to the 18-query vLLM preflight until
`live_preflight_allowed=true`.

## 9. Return These Results

Return the following small files to the local repository maintainer:

```text
$XGAP_FREEBASE_RAW_DIR/source_manifest.json
$XGAP_FREEBASE_CATALOG_DIR/manifest.json
$XGAP_FREEBASE_CATALOG_DIR/integrity_report.json
$XGAP_GRAILQA_REACHABILITY_V2/audit_summary.json
$XGAP_GRAILQA_REACHABILITY_V2/catalog_coverage.json
$XGAP_GRAILQA_REACHABILITY_V2/retrieval_metrics.json
$XGAP_GRAILQA_REACHABILITY_V2/prompt_reachability.json
$XGAP_GRAILQA_REACHABILITY_V2/stage_failure_counts.json
$XGAP_GRAILQA_REACHABILITY_V2/manifest_reference.json
slurm-freebase-catalog-v2-${JOB_ID}.out
```

Keep `catalog.sqlite3`, entity JSONL files, `retrieval.jsonl`, and
`reachability.jsonl` on persistent CWRU storage. Their hashes are recorded in
the returned manifests.
