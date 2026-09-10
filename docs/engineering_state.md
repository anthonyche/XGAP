# XGAP current engineering loop

Updated: 2026-09-10. Owner: task 01a085a5-3722-78e2-aab8-c19ef093c36d.

## Workspace and scope

- Authoritative working repository: `/Users/anthonyche/Developer/XGAP`.
- Branch at entry: `codex/m13e4-grailqa-semantic-paper-protocol`; base `a91aed6`.
- The ChatGPT mirror repository is stale; synced `sources/` remain read-only.
- Goal: complete the agentic federated system through measured milestones,
  preserving prior scientific choices and accepted/raw experiment artifacts.
- No subordinate agents requested or spawned in this task.

## User schedule and stopping condition

The user-requested overnight pause ended at **2026-09-10 10:00 +08:00**.
Work resumed at 10:03 and the existing `xgap` heartbeat was restored to ACTIVE
hourly cadence. D198 had completed at commit `65ad96c` before the pause.
Do not treat the old overnight stopping instruction as a current pause.
Local scheduled execution needs this Mac and the Codex app available.

The agent cannot directly push to ChatGPT mobile or verify phone delivery.
Do not claim a phone push occurred. The app's Goal is still active: the goal
tools expose no pause operation, and CUA explicitly prohibits controlling the
Codex app itself. No alternate UI/database workaround is permitted. At the
next explicitly requested pause, the user can click the Goal progress row's pause control.
Do not mark the broad system goal complete or blocked to imitate a pause.
The scheduled morning recovery has occurred; normal authorized work continues.

## Current milestone

D200 local software acceptance is complete: read-only reconstruction of the
guarded inline development run, including source/context, provider, semantic,
token/lifecycle and evaluation layers. See
`docs/report/grailqa_guarded_whole_run_evidence_v1.md`. D199 fixes v1 as the
control catalog; no actual new model run has been measured or admitted.

The implementation reconstructs complete actual offline-runner fixtures and
passes **184 focused tests in 17.39s**. Full regression completed in its
original exec session 59949: **2700 passed, 37 skipped in 625.92s**. Do not
restart it. The harness and all 19 acceptance examples pass. Receipt:
`experiments/artifacts/d200_guarded_whole_evidence_local_20260910.json`.
The narrow environment fix accepts numeric JSON 0/1 versus the bundle's
normalized floats while rejecting booleans; frozen specs are intact.
Accepted producer **6b32b973d4fd1a979b714570d3edcd2e684c1b07** is committed
and successfully pushed to the existing remote branch. The working tree was
clean after the commit. No source changed after the successful full suite.

The exact-commit remote operator package and one-step instructions are in
`docs/report/grailqa_inline18_cwru_handoff_20260910.md`. The local ZIP is ready,
but has not been uploaded or executed. It fixes v1, preserves prelaunch catalog
and tokenizer pins, submits once to an isolated checkout, then supports a
separate post-completion D200 reconstruction. Server-side upload/start has been
requested because both browser control and the one SSH route are unavailable.

User steering (September 10): explain XGAP versus graph-guided RAG, identify
which pipeline stage the catalog serves, and stop treating catalog work as the
whole system. After D200 acceptance, prioritize the fixed-v1 real inline18
experiment and actual federated answers. Metadata-index reuse and entity
coverage diagnosis remain separate, bounded work; do not repeat the same scan.

During the full suite, dedicated OnDemand shell tabs 366873210 (hpc5) and
366873213 (hpc7) appeared, but browser control timed out before any server
command was sent. No job was submitted or remote file written. CUA resets can
renumber browsers: most recent inventory was Chrome browser 1 and in-app
browser 2, not their earlier IDs. The new terminal tabs lack providerTabId in
the latest inventory; do not assume they are controllable. The user-owned
366872568 terminal still has a providerTabId and hpc8 title, but avoid typing
into it while the user is active. The earlier file-editor route remains a
separate read-only fallback. Native foreground typing remains unsuitable.
The subsequent read of existing file tab 366873192 also timed out before
returning any page content. This is a browser-control failure, not evidence of
expired authentication. No new remote action has been attempted. Prepare the
exact-commit runnable handoff and continue independent answer-execution work;
do not keep creating tabs or repeat unchanged catalog/audit work.
The alternate provider-ID lookup returned tab-not-found. A single strict,
noninteractive SSH connection to Pioneer port 22 timed out before any remote
command ran. No authentication setting was changed or credential requested.

Concrete next answer-chain gap: `freebase_sources.parquet_row_to_triple`
intentionally drops plain/datatype-bearing literals for catalog compatibility.
It cannot serve unchanged as the fact reader for dates/numeric filters. Build
the target-data path with full RDF term identity and independent answer checks;
do not change the old catalog parser, derive facts from gold, or substitute
another catalog/audit cycle. The D200 and handoff turn is progress: full
acceptance completed, source committed/pushed, exact runnable package prepared,
and the remaining remote-control and typed-fact gaps were directly observed.

D199 / H1 catalog comparison observation is complete. Job **3796988** finished
successfully; the actual report has **zero coverage gains and zero losses** in
all 15 stage/component cells. Both catalogs retain joint availability 10/18,
Top-20 joint retrieval 6/18, and deployed-prompt joint reachability 5/18.
All 18 entity ID lists, including order, are identical at all three stages.
Launch/log/status/report identities agree; all 15 counts were reconstructed
from the report's per-query rows. This is a real development observation,
not a fresh whole-run/source audit. The full report was read in the browser
session; only a compact derived receipt is durable locally. See
`docs/report/grailqa_catalog_comparison_3796988.md` and its linked receipt.
No executable source changed or full regression was repeated in this observation.

D198 adds read-only admission of the complete retained inline provider history:
all materializations, typed/grounded feedback, exact repair payloads, token
receipt and transport order, raw/consumed responses, invocation copies and
query state seals. This is a provider evidence component, **not whole-run
admission**, semantic accuracy, recomputed token counts, or server identity.
See `docs/report/grailqa_inline_evidence_v1.md`.
Focused regression: **215 passed in 3.13 seconds** (41 new tests).
Harness + all 19 acceptance examples pass. Full offline regression: **2587
passed, 37 skipped in 596.33 seconds**. D198 local software acceptance is complete.
Evidence: `experiments/artifacts/d198_inline_evidence_local_20260909.json`;
full log: `/tmp/xgap-inline-evidence-20260909/full-regression.log`.
The final handoff is `docs/report/xgap_implementation_report_20260909_evening.md`.
The scheduled recovery has now occurred.

D197 / H3 software acceptance is complete: inline slot annotations are
materialized into the existing guarded semantic pipeline, with original/derived
response evidence and deterministic replay. See
`docs/report/grailqa_inline_grounding_v1.md` and
`experiments/artifacts/d197_inline_grounding_local_20260909.json`.
Focused regression: **297 passed in 2.28 seconds**. Final full regression:
**2546 passed, 37 skipped in 608.62 seconds**. The harness check and all 19
acceptance examples pass. Actual Qwen schema acceptance, token fit and semantic
effectiveness remain unmeasured; H3's empirical comparison is still open.

The first full attempt was 2545 passed / 1 failed / 37 skipped. A historical
review test compared its frozen provider hash to later source. The test now
reads the original source from that review's declared commit, preserving every
old artifact/hash. The full suite was rerun after this test-only correction.
Do not repeat successful acceptance without a new code change or concern.

Prior completed milestone, commit `13dd4ba`: D196 / H2 preserves RDF term and resource identity through explicitly selected
native compilation, HTTP execution, runtime fragment wiring, and answer projection.
Implementation and 153 focused tests pass (one live gate skipped).
Full regression: **2503 passed, 37 skipped in 604.92 seconds**.
The harness check and all 19 acceptance examples also pass.
The new live Fuseki test is explicitly gated and not yet measured.

Current full regression log: `/tmp/xgap-inline-evidence-20260909/full-regression.log`.
Python with pytest 9.0.2 / RDFLib 7.1.4:
`/tmp/xgap-directed-tests.qU2YfW/venv/bin/python`.

## Remote state

OnDemand is open in Chrome at
`https://ondemand-pioneer.case.edu/pun/sys/shell/ssh/pioneer.case.edu`.
The user returned a fresh scheduler record for **3796988: COMPLETED, 0:0,
03:56:26**, start `2026-09-09T04:35:55`, end `2026-09-09T08:32:21` in the
scheduler's unverified time zone. This record was also read in the terminal.
Its log is
`/home/hxc859/XGAP-m15-465e2e2/slurm-xgap-grailqa-catalog-compare-3796988.out`;
the final five-line log was read through the portal editor and reports CLI
success with the same comparison hash as the status and report.
The job belongs to the previous e39b98e CPU catalog comparison and is terminal.
Keep its outputs intact. No new remote job has been submitted by this task.
There is no local SSH config. Native browser input can be delayed and drops
some special characters; do not send compound or state-changing commands
through that route until exact input is verified. Read-only attempts produced
two harmless `scontrol` syntax errors, not a change to the running job.

The restored login now works through a fresh extension-backed file tab. Raw
file links return Chrome `ERR_BLOCKED_BY_CLIENT`; the portal's ordinary Edit
view exposes file contents. Read/select/copy only, never Save. Its Save button
remained disabled after copying. Use a separate task tab, because the user may
navigate the shared tab during other work. Native foreground terminal input
remains unverified; do not type into a user-changing window or infer execution.
Do not treat retained screen text as a newly executed scheduler observation.

## Next actions

1. Continue the document reading inventory; long historical material is
   indexed but not all paragraphs have been reviewed. All three known source
   PDFs have now been read in full, with selected figures/formulas checked;
   proof verification and experiment reproduction are separate. Markdown
   progress is 63 full / 7 selected sections / 11 detailed reviews pending.
2. Preserve the 3796988 negative comparison. Do not repeat this rebuild or a
   GPU comparison of unchanged candidate sets. For inline-interface development,
   keep the old v1 catalog fixed; diagnose entity mention/alias/selection-rank
   exclusions separately from retrieval/prompt truncation, without gold-fed data.
3. Extend D198's provider evidence component to independent whole-run admission
   for the new materialized-response contract: producer/spec/population,
   catalog/retrieval, environment/lifecycle, tokenizer parity, metrics and gold
   isolation still need their complete evidence chain. Keep the new inline bundle/spec separate.
   Establish vLLM schema compatibility and actual request fit with the existing
   bounded probes while holding the v1 catalog fixed. No running job was found
   for this completed comparison; retain exact producer checkouts and use the
   existing staging/run authority before any new bounded experiment.
4. Prepare a real two-engine answer admission over inference-owned data.
   Current typed-row results are not full GrailQA execution or accuracy.

## Continuation

Existing automation `xgap` was updated, not duplicated, and has returned to
hourly bounded cycles. Stay quiet without meaningful change. The broad goal
remains in progress; the overnight pause is complete.

## Persistent rules

Never use gold to construct retrieval/deployment data. Keep all evaluation
denominators and failed records. Do not rerun the accepted FinBench campaign,
change its population, or claim independent instance-memory gains from the
recorded fixed-route tie. External failures are observations without silent
retry. Ask the user only for unavailable credentials/network/server action,
external artifacts, or a material scientific decision; routine authorized
implementation and testing continue autonomously.
