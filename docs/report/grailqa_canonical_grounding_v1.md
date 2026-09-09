# GrailQA canonical grounding: isolated development repair

## Scope and implementation

This opt-in repair addresses a concrete validation defect, not a measured model
improvement. A candidate could declare a visible class for a component whose
actual AST label was different or absent and obtain a finite semantic score.
A bad grounding declaration could also discard other parsed candidates in the
same response. New candidate metrics exclude invalid rows rather than counting
an exact-looking but rejected row as successful recall.

The policy is `grailqa_canonical_ast_grounding_v1`; the new development spec is
`experiments/specs/grailqa_semantic_preflight_canonical_grounding_v1_cwru_qwen3_32b.json`,
with freeze hash
`288101e5092ada216a8e9f63a045cd19ef1a949ec2299409d7013f60b0d6ba79`.
Only experiment/run identities and this explicit policy differ from the
output-contract-v1 spec. Model, prompt, questions/order, old catalog, retrieval,
candidate/token/repair budgets, timeout, epsilon and no-backend boundary remain.

- `grailqa_candidate_grounding.py` checks actual typed AST components, all
  additional visible schema terms and recursively declared entity literals.
  Exact endpoint-role-derived types remain permitted; unseen types or invented
  identity literals do not. No AST rewriting or gold input is introduced.
- The inference wrapper retains each parsed candidate and its error, while
  only accepted grounding reaches semantic scoring. Query anchors, duplicate
  IDs/caps and malformed JSON/AST envelopes still fail closed. Existing provider
  repair bounds are unchanged; isolation itself spends no call.
- The evaluator keeps all question denominators, with separate generated,
  validated-grounded, rejected and unassessed counts. Component accuracy is
  explicitly conditional on validated-grounded candidates. Query states retain
  the original rows; `rejected_candidates.jsonl` makes exclusions explicit.
- The guarded lifecycle binds policy in launch/spec/state/status/metrics.
  Unknown/mixed policies fail before inference or evaluation reference reads.
  The legacy entrypoint refuses the new spec rather than silently ignoring it.
  Default legacy outputs remain unchanged. D185's two historical source hashes
  are verified at its recorded base commit, not rewritten to match later code.

## Current real result and remaining gaps

User-supplied status/metrics for GPU `3796877` at `8bcf919` report completed
development inference, 17/18 provider successes, one candidate-bearing query,
three candidate rows (one finite score), and **zero reference matches**.
There is one local token refusal; all 18 tokenization probes completed without
server-tokenization refusal. The 13 unavailable reference contexts remain
8 catalog / 4 retrieval / 1 prompt-visibility cases; the five reachable queries
still yield zero matches and zero candidate-bearing queries. Aggregate metrics
alone do not locate every new candidate failure. No independent audit or paper
admission is inferred from this attachment. This run predates the new policy.

The old M5 OUT-only lowering check remains in candidate validation. IN support
and a complete semantic-validation versus executable-capability separation are
**not** implemented by this repair. Public schema/alias enrichment, ranking and
packing also remain separate versioned work. CPU eligibility-backfill might
produce no coverage gain: do not predict a gain from synthetic tests. All
missing FinBench-semantic / GrailQA-physical and original EQ1–EQ5 comparisons
remain obligations. No automatic GPU rerun or full150 authority is created.

### Read-only uploaded-record replay

Both uploaded JSONL files contain 18 rows. Their hashes are recorded in
`experiments/artifacts/grailqa_guarded_3796877_offline_diagnostic_20260909.json`.
The existing request reconstruction verifies payload and prompt-view hashes,
question identity and response linkage for every row. No source was edited,
no reference content opened and no external call made.

The 49 recorded raw candidates reproduce 16 legacy grounding-rejected
questions, one provider failure and one grounding-passed question. That last
question's three candidates declare class IDs that differ from their actual
source labels; the old finite score is therefore not evidence of correctness.
New-policy replay rejects those mismatches. It preserves four other individually
grounded candidates from two previously rejected packets; three pass existing
validation, while one retains the M5 IN-lowering failure. Shared-anchor errors
still reject three packets (seven unassessed candidates), and 38 individually
assessed candidates fail grounding. These are diagnostic counts, not new
semantic accuracy/admissibility or an independently admitted producer result.

The guard failure is specifically a **repair** refusal: first generation sent
4,800 input tokens, produced 4,096 output tokens with `finish_reason=length`,
and returned 121,184 characters including long whitespace. Its repair request
would exceed the input allowance and was not sent. Do not describe this as
the original generation never reaching the server, or increase budgets silently.

## Verification

The focused suites pass 101 candidate/inference/lifecycle tests and 55 shell
handoff/historical-contract tests. Synthetic cases cover mixed good/bad siblings,
canonical relaxation, actual/declaration mismatch, recursive identity literals,
unclaimed conditions, ambiguous properties, shared-envelope errors, malformed
entity declarations, unchanged provider call ledgers and full denominators.
Full offline acceptance passes **2214 tests, 36 skipped, 593.96 seconds**.
Three offline examples (LLM boundary, semantic audit, selective resolution),
guarded CLI help, shell syntax and whitespace checks pass. Skipped/live behavior
remains unverified. No external model/backend call was made in these tests.

## CPU-only CWRU handoff

The already verified and pushed class-identity fix is **e39b98e**, separate from
this new grounding policy. GPU `3796877` has completed; do not switch a checkout
if any other job still uses it. Paste only the block below, without shell prompt
characters. It submits one fresh CPU comparison, not another GPU run, and leaves
both prior results and the old catalog untouched. Server execution remains a
manual user action; the agent has not submitted this job.

```bash
bash <<'BASH'
set -euo pipefail
module load Miniconda3
cd "$HOME/XGAP-m15-465e2e2"

test -z "$(git status --porcelain --untracked-files=all)" || {
  echo "checkout is dirty; stop"
  exit 1
}
XGAP_CPU_COMMIT=e39b98e109870f8910c1f2ec98348965bd272f30
git fetch origin codex/m13e4-grailqa-semantic-paper-protocol
git switch --detach "$XGAP_CPU_COMMIT"
test "$(git rev-parse HEAD)" = "$XGAP_CPU_COMMIT"
test -z "$(git status --porcelain --untracked-files=all)"

export XGAP_REPO_ROOT="$PWD"
export XGAP_PYTHON="$HOME/venvs/xgap-core/bin/python"
export XGAP_GRAILQA_REPAIR_RUNNER_COMMIT="$XGAP_CPU_COMMIT"
export XGAP_GRAILQA_LEGACY_CATALOG="$HOME/xgap-data/freebase/grailqa-local-catalog-v1/preflight18"
export XGAP_FREEBASE_PARQUET_ROOT="$HOME/xgap-data/freebase/raw/hf-archival-parquet"
export XGAP_FREEBASE_SOURCE_MANIFEST="$HOME/xgap-data/freebase/raw/source_manifest.json"
unset XGAP_LOCAL_CATALOG_STAGING_ROOT

test -x "$XGAP_PYTHON"
test -d "$XGAP_GRAILQA_LEGACY_CATALOG"
test -d "$XGAP_FREEBASE_PARQUET_ROOT"
test -f "$XGAP_FREEBASE_SOURCE_MANIFEST"
XGAP_CPU_JOB=$(sbatch --parsable --export=ALL scripts/slurm/run_grailqa_catalog_comparison.sbatch)
echo "cpu_catalog_comparison_job_id=$XGAP_CPU_JOB"
echo "commit=$XGAP_CPU_COMMIT"
BASH
```

The user has supplied `query_states.jsonl` and `guard_diagnostics.jsonl` from
`/home/hxc859/XGAP-m15-465e2e2/runs/cwru-grailqa-guarded-3796877/results/grailqa-guarded-preflight/`.
No further upload or regenerated inference is required for the diagnosis above.
