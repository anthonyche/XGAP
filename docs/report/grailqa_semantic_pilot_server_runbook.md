# GrailQA Semantic Pilot Server Runbook

This runbook assumes the repository is `~/XGAP`. The server performs no source
editing or experiment selection. Run the commands in order.

## 1. Synchronize Code

```bash
cd ~/XGAP
git pull --ff-only
git status --short
```

`git status --short` must print nothing. Record the commit:

```bash
git rev-parse HEAD
```

## 2. Enter The Repository

```bash
cd ~/XGAP
```

## 3. Activate The Python Environment

Use the same Python 3.10+ environment already used for XGAP. If the server has
a repository virtual environment:

```bash
test ! -f .venv/bin/activate || source .venv/bin/activate
python --version
```

The runner uses `PYTHONPATH=src` and does not require an editable install.

## 4. Download And Verify The Frozen Artifacts

The dataset bodies are intentionally excluded from Git. Download the fixed
public sources, rebuild the deterministic v2 audit prerequisite, pilot bundle,
and inference catalog, and verify them against the frozen spec:

```bash
bash scripts/server/fetch_grailqa_m13d_artifacts.sh
```

On a server with `/data`, the command first prepares this layout automatically:

```text
/home/chl/xgap-data -> /data/chl/xgap-artifacts
/home/chl/xgap-data/grailqa-m13d-v1
```

The repository remains at `/home/chl/XGAP`. Only the large download cache,
unpacked public dataset, and temporary build products use `/data`. If ordinary
user permission cannot create `/data/chl/xgap-artifacts`, the script tries the
narrow directory-creation step with `sudo` and may request the server password.
If sudo is unavailable or fails, it prints the equivalent manual command.

The first run may take several minutes. Later runs reuse verified downloads
and exit immediately when the installed artifacts already match. No DashScope
credential is used here. To prepare or inspect the storage link separately:

```bash
bash scripts/server/prepare_xgap_data_storage.sh
```

To check without downloading or rebuilding:

```bash
bash scripts/server/fetch_grailqa_m13d_artifacts.sh --verify-only
```

## 5. Export The Credential

The secret value is server-specific and must be supplied by the human:

```bash
export DASHSCOPE_API_KEY='<server DashScope key>'
export DASHSCOPE_BASE_URL='https://dashscope.aliyuncs.com/compatible-mode/v1'
```

Use the endpoint matching the key's DashScope region. Neither value is written
to run artifacts.

## 6. Check Readiness

```bash
bash scripts/check_grailqa_semantic_pilot_ready.sh
```

Continue only when the final line is `READY=true`. The credential-gated smoke
is the provider reachability check.

## 7. Run The Three-Query Smoke

```bash
bash scripts/run_grailqa_semantic_pilot_smoke.sh
```

The script prints its timestamped smoke directory. Verify that it finishes with
the Markdown result summary and reports three accounted queries. This smoke
uses the exact frozen prompt, model, catalog, method, and first three pilot IDs;
it does not write to the paper-pilot directory.

## 8. Run The Full Frozen Pilot

```bash
bash scripts/run_grailqa_semantic_pilot.sh
```

The command prints the git commit, spec hashes, pilot-bundle hash, catalog hash,
model, query count, and output directory before the first request. It runs the
150 existing IDs and does not accept parameter overrides.

## 9. Resume After An Interruption

Use the same credential and run:

```bash
bash scripts/run_grailqa_semantic_pilot.sh --resume
```

Resume preserves the original run identity, does not repeat successful API
calls, skips deterministic terminal retrieval misses, and retries provider
failures/unprocessed questions.

## 10. Verify Completion

```bash
cd ~/XGAP
python - <<'PY'
import json
from pathlib import Path

root = Path('runs/m13d-grailqa-semantic-pilot-v1')
progress = json.loads((root / 'progress.json').read_text())
manifest = json.loads((root / 'run_manifest.json').read_text())
print('status=', progress['status'])
print('query_count=', progress['query_count'])
print('accounted=', progress['accounted_query_count'])
print('run_id=', manifest['run_id'])
print('summary=', root / 'result_summary.md')
PY
```

Success means `status=complete`, `query_count=150`, `accounted=150`, and all
files listed in `result_summary.md` exist. Non-empty `failures.jsonl` is valid
experiment output, not an instruction to alter the frozen method.

## 11. Return Results

After the server run, send back:

1. complete terminal final summary;
2. `runs/m13d-grailqa-semantic-pilot-v1/result_summary.md`;
3. `runs/m13d-grailqa-semantic-pilot-v1/metrics.json`;
4. `runs/m13d-grailqa-semantic-pilot-v1/run_manifest.json`;
5. `runs/m13d-grailqa-semantic-pilot-v1/failures.jsonl` if non-empty;
6. any readiness/smoke errors.

There is no need to manually inspect or return every JSONL file unless later
analysis requests one.
