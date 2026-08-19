# CWRU vLLM Runbook

## Assumptions

There is no Codex process on CWRU. Code is prepared locally, committed, and
synchronized through Git. `/home/hxc859` is shared across login and compute
nodes, so both `/home/hxc859/venvs/xgap-vllm` and the Hugging Face cache at
`/home/hxc859/.cache/huggingface` are reusable across `gput072`, `gput073`,
and any other eligible H100 node. These names are operational examples, not
node pins; Slurm must choose the host.
The vLLM process itself exists only inside one Slurm job.

CWRU OnDemand may be preferable when direct SSH from China is slow; a regular
login-node shell is also valid. XGAP does not encode VPN or compute-host
assumptions.

## 1. Synchronize Git

From the CWRU login node or OnDemand terminal:

```bash
cd "$HOME/XGAP"
git fetch origin
git pull --ff-only
git log -1 --oneline
git status --short
```

The final command must be empty. The batch wrapper rejects dirty experiment
checkouts by default.

## 2. Confirm Offline Artifacts

Set the external M13-E1 artifact locations when they are outside the checkout:

```bash
export XGAP_GRAILQA_CATALOG_V2="$HOME/xgap-data/grailqa-inference-catalog-v2"
export XGAP_GRAILQA_REACHABILITY_V2="$HOME/xgap-data/grailqa-reachability-v2"
```

The preflight wrapper checks the frozen 0.20 joint prompt-reachability gate
before loading the model. Until catalog-v2 passes, submission exits without
performing inference.

## 3. Submit The 18-Query Preflight

```bash
cd "$HOME/XGAP"
JOB_ID=$(sbatch --parsable scripts/slurm/run_grailqa_semantic_preflight_v2.sbatch)
echo "$JOB_ID"
```

The default time limit is four hours. Slurm options may override it without
editing the repository:

```bash
JOB_ID=$(sbatch --parsable --time=06:00:00 \
  scripts/slurm/run_grailqa_semantic_preflight_v2.sbatch)
```

Do not add a node constraint. `-C gpu2h100` lets Slurm choose any eligible
H100 host.

## 4. Check Queue And Job

```bash
squeue -j "$JOB_ID"
scontrol show job "$JOB_ID"
```

After scheduling, the first lines record the chosen hostname, Slurm job ID,
and Git commit.

## 5. Monitor Logs

The Slurm stream is:

```bash
tail -f "slurm-xgap-grailqa-preflight-${JOB_ID}.out"
```

The job-owned copies are:

```bash
RUN_ROOT="$HOME/XGAP/runs/cwru-grailqa-preflight-v2-${JOB_ID}"
tail -f "$RUN_ROOT/job.log"
tail -f "$RUN_ROOT/vllm.log"
```

Readiness failure automatically prints the final vLLM log lines,
`nvidia-smi`, and process status into the job log.

## 6. Inspect Result

```bash
RUN_ROOT="$HOME/XGAP/runs/cwru-grailqa-preflight-v2-${JOB_ID}"
cat "$RUN_ROOT/run_status.json"
cat "$RUN_ROOT/cwru_environment.json"
cat "$RUN_ROOT/vllm_structured_smoke.json"
cat "$RUN_ROOT/results/grailqa-semantic-preflight-v2/metrics.json"
cat "$RUN_ROOT/results/grailqa-semantic-preflight-v2/run_manifest.json"
```

Success means:

- `run_status.json` reports `success` and exit code 0;
- the structured serving smoke reports `schema_valid=true`;
- the result directory contains all 18-query preflight artifacts;
- the preflight manifest contains the CWRU environment record;
- cleanup has stopped the recorded vLLM PID.

## 7. Failure And Re-run Policy

The 18-query preflight is intentionally not resumed into a partial directory.
After diagnosing a failed job, submit it again; the new Slurm job ID creates a
new immutable run directory. Do not overwrite or merge prior responses.

```bash
JOB_ID=$(sbatch --parsable scripts/slurm/run_grailqa_semantic_preflight_v2.sbatch)
```

For a cancelled job:

```bash
scancel "$JOB_ID"
```

Slurm termination reaches the wrapper's cleanup trap, which stops vLLM and
writes failure status where time permits. A future resumable experiment may be
passed to the generic wrapper only when that experiment's own protocol defines
resume semantics.

## Generic Wrapper

The infrastructure is not tied to GrailQA:

```bash
sbatch scripts/slurm/cwru_xgap_vllm.sbatch \
  <experiment-spec.json> \
  python -m <xgap.experiment.module> <arguments...>
```

This command does not authorize a 150-query run. M13-E2 freezes only the
18-query GrailQA preflight wrapper; larger runs remain separately reviewed.
