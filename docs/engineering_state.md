# XGAP current engineering loop

Updated: 2026-09-09. Owner: task 01a085a5-3722-78e2-aab8-c19ef093c36d.

## Workspace and scope

- Authoritative working repository: `/Users/anthonyche/Developer/XGAP`.
- Branch at entry: `codex/m13e4-grailqa-semantic-paper-protocol`; base `a91aed6`.
- The ChatGPT mirror repository is stale; synced `sources/` remain read-only.
- Goal: complete the agentic federated system through measured milestones,
  preserving prior scientific choices and accepted/raw experiment artifacts.
- No subordinate agents requested or spawned in this task.

## User schedule and stopping condition

User confirmed on 2026-09-09 (Asia/Shanghai): complete one verifiable milestone
before midnight, deliver an implementation report, then pause to conserve
tokens and resume at **2026-09-10 10:00 +08:00**. The existing `xgap` heartbeat
has been updated to the next 10:00 daily slot, replacing hourly overnight
wakeups. Its first morning run is instructed to restore the hourly cadence.
The local machine clock is CST +0800. Local execution needs this Mac and the
Codex app available at that time.

The agent cannot directly push to ChatGPT mobile or verify phone delivery.
Do not claim a phone push occurred. The app's Goal is still active: the goal
tools expose no pause operation, and CUA explicitly prohibits controlling the
Codex app itself. No alternate UI/database workaround is permitted. At the
milestone handoff ask the user to click the Goal progress row's pause control.
Do not mark the broad system goal complete or blocked to imitate a pause.
After the handoff, do not start another engineering milestone before the
scheduled morning recovery unless the user explicitly changes this instruction.

## Current milestone

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
No further development milestone should begin before the scheduled morning recovery.

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
The visible last scheduler record reports 3796988 RUNNING on compt303,
8 CPUs, 48 GiB, elapsed 02:53:15, four-hour limit. This is an observed
snapshot, not a completion claim. Its log is
`/home/hxc859/XGAP-m15-465e2e2/slurm-xgap-grailqa-catalog-compare-3796988.out`;
this task has not yet retrieved the log contents.
The job belongs to the previous e39b98e CPU catalog comparison. Keep its
checkout and outputs intact. No new remote job has been submitted by this task.
There is no local SSH config. Native browser input can be delayed and drops
some special characters; do not send compound or state-changing commands
through that route until exact input is verified. Read-only attempts produced
two harmless `scontrol` syntax errors, not a change to the running job.

The user restored CWRU login on 2026-09-09. The file page shows the logged-in
account and the repository directory; the target log was listed as 232 bytes,
last modified 16:36:13 CST. Claiming the browser tab still timed out, native
paste timed out, and the opened raw-log page did not return readable content.
Native terminal input remained unverified. No new scheduler command was
successfully executed by this task and no terminal job result was obtained.
Login restoration is resolved; browser/terminal interaction remains unreliable.
Do not treat retained screen text as a newly executed scheduler observation.

## Next actions

1. Continue the document reading inventory; long historical material is
   indexed but not all paragraphs have been reviewed. All three known source
   PDFs have now been read in full, with selected figures/formulas checked;
   proof verification and experiment reproduction are separate. Markdown
   progress is 63 full / 7 selected sections / 11 detailed reviews pending.
2. Observe 3796988 completion and its coverage gains/losses using bounded
   read-only logs/artifacts. Do not equate scheduler completion with success.
3. Extend D198's provider evidence component to independent whole-run admission
   for the new materialized-response contract: producer/spec/population,
   catalog/retrieval, environment/lifecycle, tokenizer parity, metrics and gold
   isolation still need their complete evidence chain. Keep the new inline bundle/spec separate.
   Establish vLLM schema compatibility and actual request fit with the existing
   bounded probes after selecting the catalog from CPU evidence. Do not launch
   another GPU experiment or change the active server checkout prematurely.
4. Prepare a real two-engine answer admission over inference-owned data.
   Current typed-row results are not full GrailQA execution or accuracy.

## Continuation

Existing automation `xgap` was updated, not duplicated, from hourly to the next
10:00 morning recovery. After that recovery it should return to hourly bounded
cycles and stay quiet without meaningful change. The broad goal remains in
progress, with the user-requested overnight pause taking precedence.

## Persistent rules

Never use gold to construct retrieval/deployment data. Keep all evaluation
denominators and failed records. Do not rerun the accepted FinBench campaign,
change its population, or claim independent instance-memory gains from the
recorded fixed-route tie. External failures are observations without silent
retry. Ask the user only for unavailable credentials/network/server action,
external artifacts, or a material scientific decision; routine authorized
implementation and testing continue autonomously.
