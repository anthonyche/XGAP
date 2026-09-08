# GrailQA Semantic Paper Runbook

## Boundary

This runbook starts only after CWRU jobs `3795088`, `3795089`, and `3795067`
reach terminal state. Do not switch the shared server checkout while any of
them is pending or running. A successful Slurm state does not create author
review, scientific selection, execution authority, or a paper result.

The 150-query run is semantic-only: Qwen3-32B proposes bounded structured
interpretations over the frozen query-local Freebase catalog. It emits no
native query, executes no backend, performs no automatic retry, and opens gold
only after all inference states are durably sealed.

Implementation-binding update: the current unapproved draft is
`grailqa_semantic_paper_protocol_draft_v2.json`. It preserves the v1 scientific
fields, source artifacts, model/prompt/schema, and all unselected author choices,
but binds the corrected runner under a new protocol ID and content hash. The
v1 draft and readiness files remain unchanged historical records. A receipt
for v1 is not authority for v2. This is **not** a revised prompt or a grant to
execute either version.

## 1. Inspect And Independently Audit Both Live Gates

Check the catalog build, catalog audit, and preflight without changing Git:

```bash
sacct -X -j 3795088,3795089,3795067 \
  --format=JobIDRaw,State,ExitCode,Elapsed,ReqMem,MaxRSS,NodeList \
  --parsable2
```

Job `3795089` is already dependency-bound to the catalog build. Its expected
output is:

```text
runs/audits/grailqa-local-catalog-pilot150-3795088-audit.json
```

After the preflight is terminal, read its producer commit from the immutable
environment record and run the CPU-only auditor:

```bash
export XGAP_REPO_ROOT="$PWD"
export XGAP_PYTHON="$HOME/venvs/xgap-core/bin/python"
export XGAP_GRAILQA_PREFLIGHT_JOB_ID=3795067
export XGAP_GRAILQA_PREFLIGHT_PRODUCER_COMMIT="$(
  "$XGAP_PYTHON" -c '
import json, sys
print(json.load(open(sys.argv[1]))["git"]["commit"])
' "$PWD/runs/cwru-grailqa-preflight-v2-3795067/cwru_environment.json"
)"

sbatch --parsable --export=ALL \
  scripts/slurm/audit_grailqa_semantic_preflight_v2.sbatch
```

Inspect both audit JSON files. Each must report `success=true`, no failed
checks, and no source-tree mutation. Do not choose paper parameters from the
18-query outcomes.

Recorded update (2026-09-08): the catalog audit passed 73 checks. The existing
preflight auditor is job `3795103` with output
`runs/audits/grailqa-semantic-preflight-v2-3795067-audit-b421a42.json`;
do not submit a duplicate. It passed 101 integrity checks but reported zero
validated candidates on all 18 queries. **Do not advance this runbook to the
150-query execution based on that audit pass.** Retained request/response
diagnosis is now complete without model calls or source mutation; present
the exact negative result for author review. The audit does not imply an
effectiveness result, reviewed preflight, scientific choice, or execution grant.

### Read-only rejection replay (no new inference)

`xgap.experiments.grailqa_preflight_replay` accepts the **inner results
directory**, not the outer CWRU run. It checks the recorded request hashes,
request/response identities, and exact prompt-view reconstruction before
replaying normalization and grounding. It prints compact per-query rejection
messages and input-file digests to stdout; it writes no artifacts, loads no
gold or catalog, and makes no model/backend/ontology-service call.

Keep the original run and audit intact. When the diagnostic source is obtained
from a later commit, retain the original checkout for its unchanged parser and
grounding imports. With the source available in the current checkout, use:

```bash
PYTHONPATH="$PWD/src" "$HOME/venvs/xgap-core/bin/python" -B \
  -m xgap.experiments.grailqa_preflight_replay \
  --run-root "$PWD/runs/cwru-grailqa-preflight-v2-3795067/results/grailqa-semantic-preflight-v2"
```

For this exact audit, the reported input hashes must match:

- `llm_requests.jsonl`: `6060078b189fa11a0fbf3840960f372b61d4306e004855c52093a3cf278363d0`
- `llm_responses.jsonl`: `557d5b250d299cd7fff3d7ffe4f13537a00f4e3bd3843b41c6731c110a3c12ce`

`status=complete` means the diagnostic ran, not that any candidate passed.
A source-identity error exits with code 2. This replay does not replace the
frozen outcome taxonomy or create a repaired live result.

The operator has completed this replay; do not repeat the server command merely
to supply the same diagnosis. Both uploaded ledgers match the hashes above.
The 17 schema-valid envelopes have 47 candidates; 16 responses miss mandatory
top-level anchors and one fails on `component_ref=n2`. The one provider-failed
response omits allowed selector/restrictor defaults. Explicit normalized-parser
wiring repairs that implementation mismatch, but its raw response still fails
the unchanged allowed-anchor check. Other candidate component references are
also invalid. This does not establish recovery or authorize 150 queries.
See `grailqa_preflight_3795067_validation.md` for the source-bound diagnosis.

No frozen prompt/schema is overwritten. A future clarification of top-level
anchor completeness, candidate-optional slots, and structural component paths
must have a distinct contract identity, offline tests, author review, and a
separate exact execution decision. Never silently fill anchors, map arbitrary
variable names to components, or import gold into inference.

Later preflight producers retain `original_inference_failure` on existing
failure rows where an original inference error exists. That additive field is
producer diagnostic data, not a replacement for the frozen top-level category
or an independent causal finding. Do not rerun preflight or rewrite old files
solely to populate it; use retained-envelope replay for the existing run.

## 2. Record The Five Author Choices

Create this record only after the author has explicitly chosen every value.
The command has no defaults for the choices:

```bash
PYTHONPATH="$PWD/src" "$XGAP_PYTHON" \
  -m xgap.experiments.grailqa_semantic_paper_admission select \
  --protocol experiments/configs/grailqa_semantic_paper_protocol_draft_v2.json \
  --repo-root "$PWD" \
  --authority-source-id '<author-owned-id>' \
  --primary-reporting-population '<explicit-value>' \
  --primary-epsilon '<explicit-value>' \
  --primary-comparator '<explicit-value>' \
  --inference-failure-estimand '<explicit-value>' \
  --interactive-clarification-role '<explicit-value>' \
  --output '<new-author-selection.json>'
```

Use `--help` to see the frozen allowed values. The system never copies the
recommended values on the author's behalf.

## 3. Review The Exact Preflight And Build Admission

After author inspection of the independent preflight audit, create a review
receipt bound to that exact audit:

```bash
PYTHONPATH="$PWD/src" "$XGAP_PYTHON" \
  -m xgap.experiments.grailqa_semantic_paper_admission review \
  --preflight-audit '<preflight-audit.json>' \
  --authority-source-id '<author-owned-id>' \
  --decision accept_exact_preflight_without_parameter_tuning \
  --output '<new-preflight-review.json>'
```

Then build the non-authorizing preexecution admission:

```bash
PYTHONPATH="$PWD/src" "$XGAP_PYTHON" \
  -m xgap.experiments.grailqa_semantic_paper_admission admit \
  --protocol experiments/configs/grailqa_semantic_paper_protocol_draft_v2.json \
  --author-selection '<author-selection.json>' \
  --repo-root "$PWD" \
  --catalog-root "$HOME/xgap-data/freebase/grailqa-local-catalog-v1/pilot150" \
  --reachability-summary "$HOME/xgap-data/freebase/grailqa-local-catalog-v1/pilot150/audit_summary.json" \
  --catalog-audit '<catalog-audit.json>' \
  --preflight-audit '<preflight-audit.json>' \
  --preflight-review '<preflight-review.json>' \
  --output '<new-preexecution-admission.json>'
```

## 4. Request And Separately Authorize One Exact Run

Build a request against the final clean runner commit. This remains
non-authorizing:

```bash
PYTHONPATH="$PWD/src" "$XGAP_PYTHON" \
  -m xgap.experiments.grailqa_semantic_paper_run request \
  --protocol experiments/configs/grailqa_semantic_paper_protocol_draft_v2.json \
  --author-selection '<author-selection.json>' \
  --repo-root "$PWD" \
  --catalog-root "$HOME/xgap-data/freebase/grailqa-local-catalog-v1/pilot150" \
  --reachability-summary "$HOME/xgap-data/freebase/grailqa-local-catalog-v1/pilot150/audit_summary.json" \
  --reachability-rows "$HOME/xgap-data/freebase/grailqa-local-catalog-v1/pilot150/reachability.jsonl" \
  --admission '<preexecution-admission.json>' \
  --run-id '<new-authority-bound-run-id>' \
  --output '<new-execution-request.json>'
```

Only the author may issue the separate exact-run authority:

```bash
PYTHONPATH="$PWD/src" "$XGAP_PYTHON" \
  -m xgap.experiments.grailqa_semantic_paper_run authorize \
  --request '<execution-request.json>' \
  --admission '<preexecution-admission.json>' \
  --authority-source-id '<author-owned-id>' \
  --decision authorize_exact_150_query_semantic_execution \
  --output '<new-execution-authority.json>'
```

## 5. Submit Once And Let The Independent Finalizer Run

Set the four exact control paths, then use the single submission helper.
Paths supplied to the helper are anchored to the submission directory before
Slurm export. Keep the authority-bound checkout fixed until both jobs terminate:

```bash
export XGAP_GRAILQA_SEMANTIC_AUTHOR_SELECTION='<author-selection.json>'
export XGAP_GRAILQA_SEMANTIC_PREEXECUTION_ADMISSION='<preexecution-admission.json>'
export XGAP_GRAILQA_SEMANTIC_EXECUTION_REQUEST='<execution-request.json>'
export XGAP_GRAILQA_SEMANTIC_EXECUTION_AUTHORITY='<execution-authority.json>'

bash scripts/server/submit_grailqa_semantic_paper_pipeline.sh
```

The helper performs a gold-blind readiness check before requesting the H100,
then submits exactly one CPU finalizer with `afterok`. The finalizer separately
audits the source run, computes the frozen query-level statistics, reconstructs
that analysis independently, and only then attempts final paper-result
admission. If the H100 job fails, the finalizer does not run and no retry is
scheduled. Only a successful final `paper_result.json` is paper evidence.

If finalizer submission fails after GPU submission, the GPU job remains
submitted. Its ID is printed immediately and preserved in
`runs/grailqa-semantic-paper-submissions/<run-id>.submission-lease/paper-job-id`.
Do not rerun the complete helper or remove the lease to obtain another GPU job.
Inspect the accepted job and failed submission first. Custom protocol and outer
run-root settings are shared with finalization, and any source-root override
must still match the submitted request and authority exactly.
