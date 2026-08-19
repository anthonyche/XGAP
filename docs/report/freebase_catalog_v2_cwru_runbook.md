# Freebase Catalog-v2 CWRU Runbook

## Scope And Frozen Source

This is an offline CPU workflow. It does not start a model, graph backend, or
GPU job. The underlying knowledge source remains Freebase; the GrailQA
processed ontology remains the benchmark schema. M13-E3A changes only the
artifact transport to the public archival Parquet representation in
`CleverThis/freebase`, frozen at immutable revision:

```text
dbb1931c2698295653effe9b980a02ab29f004e0
```

The frozen inventory contains 964 files (`default/data/0000.parquet` through
`0963.parquet`) totaling 32,476,432,840 bytes. The actual six nullable string
columns are `subject`, `predicate`, `object`, `object_type`,
`object_datatype`, and `object_language`. Catalog construction streams one
shard, one row group, and one bounded record batch at a time. It does not
materialize a decompressed N-Triples or JSONL copy.

Direct retrieval of all four documented Google-hosted Freebase objects in the
M13-E3 investigation returned HTTP 403 from CWRU Pioneer on 2026-08-19. The
archival workflow does not retry or fall back to those objects. The old
`google_rdf_gzip` mode remains available only when selected explicitly and a
locally verified RDF artifact already exists.

## 1. Synchronize Git

```bash
cd "$HOME/XGAP"
git fetch origin
git pull --ff-only
git log -1 --oneline
git status --short
```

Require an empty status for the paper build. Verify the excluded M13-D
GrailQA evaluation artifacts before catalog work:

```bash
bash scripts/server/fetch_grailqa_m13d_artifacts.sh --verify-only
test -s datasets/grailqa_audit_v2/supported_questions.jsonl
test -s datasets/grailqa_pilot_v1/inference_questions.jsonl
test -s datasets/grailqa_pilot_v1/reference_interpretations.jsonl
test -s datasets/grailqa_pilot_v1/workload_stats.jsonl
```

## 2. Configure Persistent Paths

Use persistent project storage rather than a Slurm job-local directory:

```bash
export XGAP_FREEBASE_SOURCE_MODE=hf_archival_parquet
export XGAP_FREEBASE_RAW_DIR="$HOME/xgap-data/freebase/raw"
export XGAP_FREEBASE_PARQUET_ROOT="$XGAP_FREEBASE_RAW_DIR/hf-archival-parquet"
export XGAP_FREEBASE_SOURCE_MANIFEST="$XGAP_FREEBASE_RAW_DIR/source_manifest.json"
export XGAP_FREEBASE_CATALOG_DIR="$HOME/xgap-data/freebase/catalog-v2"
export XGAP_GRAILQA_CATALOG_V2="$XGAP_FREEBASE_CATALOG_DIR"
export XGAP_GRAILQA_REACHABILITY_V2="$HOME/xgap-data/freebase/grailqa-reachability-v2"

mkdir -p "$XGAP_FREEBASE_RAW_DIR" \
  "$XGAP_FREEBASE_CATALOG_DIR" \
  "$XGAP_GRAILQA_REACHABILITY_V2"
df -h "$XGAP_FREEBASE_RAW_DIR"
```

The complete raw source needs about 32.5 GB plus filesystem overhead. The
derived SQLite and JSONL catalog needs additional persistent capacity. Export
the same variables in later login sessions or store them in a private shell
environment file. No Hugging Face token, root privilege, or GPU is required.

Install the optional Parquet reader into the active Python environment once:

```bash
python -m pip install --user "pyarrow>=15"
python -c 'import pyarrow; print(pyarrow.__version__)'
```

## 3. Run The One-Shard Smoke

Do this before starting the full archive transfer:

```bash
cd "$HOME/XGAP"
bash scripts/server/smoke_freebase_archival_parquet.sh
```

The command downloads and SHA-256 verifies only frozen shard `0000`, then
reads only its first row group. Success requires Freebase MID subjects,
English canonical names, English aliases, `type.object.type` memberships, and
English language-tagged literals. The final line is:

```text
Frozen archival Freebase Parquet smoke passed.
```

## 4. Download The Frozen Shards

```bash
bash scripts/server/download_freebase_archival_parquet.sh
```

The script enumerates only the 964 immutable URLs committed in
`experiments/artifacts/freebase_hf_archival_parquet_v1.json`. Each transfer
uses a colocated `.part` file, resumes when possible, validates exact byte size
and LFS SHA-256, then atomically renames the file. A second invocation reuses
verified final shards. It does not create a duplicate Hugging Face cache.

After all shards pass, the script writes `source_manifest.json` with source
mode, repository, revision, resolved conversion revision, schema fingerprint,
exact shard inventory, checksums, total bytes, retrieval timestamp, source
URL, and builder Git commit.

## 5. Verify The Local Source

```bash
bash scripts/server/verify_freebase_archival_parquet.sh
cat "$XGAP_FREEBASE_SOURCE_MANIFEST"
```

Verification recomputes every shard size and SHA-256 and rejects missing or
extra local `.parquet` files. Success reports 964 shards and 32,476,432,840
bytes. There is no automatic source fallback.

## 6. Submit The CPU Catalog Build

```bash
JOB_ID=$(sbatch --parsable --export=ALL \
  scripts/slurm/build_freebase_catalog_v2.sbatch)
echo "$JOB_ID"
```

The default request is 16 CPU cores, 128 GB memory, and 48 hours, with no GPU.
Scheduler resources can be overridden without editing the repository:

```bash
JOB_ID=$(sbatch --parsable --export=ALL \
  --cpus-per-task=24 --mem=192G --time=3-00:00:00 \
  scripts/slurm/build_freebase_catalog_v2.sbatch)
```

The job records source mode, repository, immutable revision, shard manifest,
Git commit, host, and CPU allocation. It validates the source, reuses the
existing M13-E3 Catalog-v2 extraction and schema, validates SQLite and FTS5,
runs the unchanged 35,439-query and frozen-150 M13-E3 audit, and emits the
separate archival compatibility report. No model is called.

## 7. Monitor The Job

```bash
squeue -j "$JOB_ID"
scontrol show job "$JOB_ID"
tail -f "slurm-freebase-catalog-v2-$JOB_ID.out"
```

A builder retry reuses verified raw shards. A complete catalog with matching
inputs is validated and reused. Replacing a complete catalog with `--force`
is intentionally a manual decision.

## 8. Inspect Reachability And Compatibility

```bash
cat "$XGAP_FREEBASE_CATALOG_DIR/manifest.json"
cat "$XGAP_FREEBASE_CATALOG_DIR/integrity_report.json"
cat "$XGAP_GRAILQA_REACHABILITY_V2/audit_summary.json"
cat "$XGAP_GRAILQA_REACHABILITY_V2/catalog_coverage.json"
cat "$XGAP_GRAILQA_REACHABILITY_V2/retrieval_metrics.json"
cat "$XGAP_GRAILQA_REACHABILITY_V2/prompt_reachability.json"
cat "$XGAP_GRAILQA_REACHABILITY_V2/stage_failure_counts.json"
cat "$XGAP_GRAILQA_REACHABILITY_V2/archival_source_compatibility.json"
```

Success means the catalog is `complete`, integrity is `ok`, the source
manifest verifies exactly, and both frozen workload counts are exact. The
compatibility report must state pilot and all-supported missing reference
MIDs, missing ontology relations/types, and joint catalog coverage. The
unchanged M13-E3 audit may produce either a scientific GO or NO-GO at its
frozen 0.20 prompt-reachability gate; a NO-GO is not source corruption.

## 9. Return These Results

Return these small files to the repository maintainer:

```text
$XGAP_FREEBASE_RAW_DIR/source_manifest.json
$XGAP_FREEBASE_CATALOG_DIR/manifest.json
$XGAP_FREEBASE_CATALOG_DIR/integrity_report.json
$XGAP_GRAILQA_REACHABILITY_V2/audit_summary.json
$XGAP_GRAILQA_REACHABILITY_V2/catalog_coverage.json
$XGAP_GRAILQA_REACHABILITY_V2/retrieval_metrics.json
$XGAP_GRAILQA_REACHABILITY_V2/prompt_reachability.json
$XGAP_GRAILQA_REACHABILITY_V2/stage_failure_counts.json
$XGAP_GRAILQA_REACHABILITY_V2/archival_source_compatibility.json
$XGAP_GRAILQA_REACHABILITY_V2/manifest_reference.json
slurm-freebase-catalog-v2-<job-id>.out
```

Keep the 32.5 GB raw shards, `catalog.sqlite3`, entity JSONL files,
`retrieval.jsonl`, and `reachability.jsonl` on persistent CWRU storage. Their
identities are represented by the returned manifests.
