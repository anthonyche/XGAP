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
150-query execution based on that audit pass.** First diagnose retained
request/response artifacts without model calls or source mutation and present
the exact negative result for author review. The audit does not imply an
effectiveness result, reviewed preflight, scientific choice, or execution grant.

## 2. Record The Five Author Choices

Create this record only after the author has explicitly chosen every value.
The command has no defaults for the choices:

```bash
PYTHONPATH="$PWD/src" "$XGAP_PYTHON" \
  -m xgap.experiments.grailqa_semantic_paper_admission select \
  --protocol experiments/configs/grailqa_semantic_paper_protocol_draft_v1.json \
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
  --protocol experiments/configs/grailqa_semantic_paper_protocol_draft_v1.json \
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
  --protocol experiments/configs/grailqa_semantic_paper_protocol_draft_v1.json \
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
