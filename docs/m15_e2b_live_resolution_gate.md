# M15-E2B CWRU Live Resolution Gate

## Purpose and claim boundary

M15-E2B verifies one bounded non-entity semantic-resolution tool call against
the frozen CWRU Qwen3-32B vLLM deployment. It does not measure answer quality,
compare optimizers, resolve entity identity, execute a graph query, or establish
a paper result. All outputs remain `paper_result=false`.

The request contains one predicate hole, four predeclared candidate IDs, and
two immutable constraints: the clarified Alice Smith identity and the one-month
time window. Any nonempty unique subset of those four IDs is a valid protocol
response. The model cannot introduce an ID, mark a binding authoritative,
change a hard constraint, or emit native query text.

## Execution contract

- one H100 GPU selected by Slurm; no host is hard-coded;
- one cached `Qwen/Qwen3-32B` revision served on loopback only;
- one M15 LLM tool call and one inference request;
- zero repair calls, zero automatic retries, and no fallback request;
- 60-second provider timeout and 256 output-token cap;
- 45-minute Slurm limit, including model startup and bounded shutdown;
- `/v1/models` readiness polling is lifecycle observation, not inference;
- the older generic structured-output smoke is intentionally not run because
  it would add a second inference request.

Before model startup, the job validates the clean Git checkout, frozen
experiment spec, deployment contract, model bundle, prompt/schema hashes,
dynamic candidate enumeration, token budget, and exact request-payload hash.
The provider call then runs through the ordinary `GoalLoop`, typed LLM tool,
and execution-memory path. A provider error is persisted with its spent call,
latency, and token cost and stops the job without retry.

## Local acceptance

The local gate uses a fake transport only. Tests cover exact spec and preflight
reconstruction, identity exclusion, dirty checkout rejection, one-call success,
costed malformed output, duplicate-ID rejection after provider parsing,
tampered preflight, environment drift, bounded Slurm syntax, successful
independent audit, and post-run artifact tampering. The provider-facing schema
omits `uniqueItems` because vLLM 0.11.1 cannot compile it; deterministic
validation retains the uniqueness contract. The targeted provider,
live-resolution, and selective-resolution regression passes 32 tests.

## CWRU execution

Run only after checking out the exact commit supplied with the gate and
confirming a clean worktree:

```bash
cd "$HOME/XGAP-m15-465e2e2"

test -z "$(git status --porcelain)" || {
  echo "checkout is dirty; stop"
  exit 1
}

sbatch --parsable \
  --export=ALL,XGAP_PYTHON="$HOME/venvs/xgap-core/bin/python" \
  scripts/slurm/run_m15_live_resolution.sbatch
```

The run root is
`runs/cwru-m15-live-resolution-<job-id>`. After Slurm reports `COMPLETED 0:0`,
run the independent auditor from the same exact commit:

```bash
XGAP_E2B_RUN="$PWD/runs/cwru-m15-live-resolution-<job-id>"
XGAP_E2B_AUDIT="$PWD/runs/audits/cwru-m15-e2b-live-resolution-<job-id>-audit.json"

mkdir -p "$PWD/runs/audits"
test ! -e "$XGAP_E2B_AUDIT" || {
  echo "audit output already exists; stop"
  exit 1
}

PYTHONPATH="$PWD/src" \
"$HOME/venvs/xgap-core/bin/python" \
  -m xgap.experiments.m15_live_resolution_evidence \
  --run-root "$XGAP_E2B_RUN" \
  --repo-root "$PWD" \
  --expected-commit <exact-40-hex-commit> \
  --output "$XGAP_E2B_AUDIT" \
  > "$XGAP_E2B_AUDIT.stdout"
```

The first CWRU attempt, job `3792284` at exact commit `953f15f`, passed runtime,
GPU, model-startup, and readiness checks, then received HTTP 400 before
generation because vLLM rejected `uniqueItems`. It spent one external call,
made no repair or retry, and produced zero tokens. Preserve that failed run and
do not audit or rerun it.

Replacement job `3792307` at exact clean commit `a2ed618` completed on
`gput073`. It returned the in-set `predicate:transferred_to` candidate through
one goal/tool/provider call in 1.877 seconds, with 452 input and 21 output
tokens, zero repairs/retries, no native query, and preserved hard constraints.
The independent read-only audit passed 127/127 checks with no mutation.
Preserve this accepted run and do not submit another E2B job.

## Required evidence

The independent auditor reconstructs the frozen request and checks the exact
commit; CWRU runtime, H100, model revision, loopback endpoint, and prompt/model
hashes; one successful tool and provider call; zero repairs and retries;
bounded non-authoritative output; hard-constraint preservation; exact goal,
memory, and invocation links; service shutdown; artifact inventory; and an
unchanged run-tree digest. The live gate is accepted only when every check
passes and `run_tree_mutated=false`.
