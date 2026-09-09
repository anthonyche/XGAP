# XGAP current engineering loop

Updated: 2026-09-09. Owner: task 01a085a5-3722-78e2-aab8-c19ef093c36d.

## Workspace and scope

- Authoritative working repository: `/Users/anthonyche/Developer/XGAP`.
- Branch at entry: `codex/m13e4-grailqa-semantic-paper-protocol`; base `a91aed6`.
- The ChatGPT mirror repository is stale; synced `sources/` remain read-only.
- Goal: complete the agentic federated system through measured milestones,
  preserving prior scientific choices and accepted/raw experiment artifacts.
- No subordinate agents requested or spawned in this task.

## Current milestone

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

Current full regression log: `/tmp/xgap-inline-20260909/full-regression-final.log`.
Python with pytest 9.0.2 / RDFLib 7.1.4:
`/tmp/xgap-directed-tests.qU2YfW/venv/bin/python`.

## Remote state

OnDemand is open in Chrome at
`https://ondemand-pioneer.case.edu/pun/sys/shell/ssh/pioneer.case.edu`.
The visible last scheduler record reports 3796988 RUNNING on compt303,
8 CPUs, 48 GiB, elapsed 01:48:43, four-hour limit. This is an observed
snapshot, not a completion claim. Its log is
`/home/hxc859/XGAP-m15-465e2e2/slurm-xgap-grailqa-catalog-compare-3796988.out`;
this task has not yet retrieved the log contents.
The job belongs to the previous e39b98e CPU catalog comparison. Keep its
checkout and outputs intact. No new remote job has been submitted by this task.
There is no local SSH config. Native browser input can be delayed and drops
some special characters; do not send compound or state-changing commands
through that route until exact input is verified. Read-only attempts produced
two harmless `scontrol` syntax errors, not a change to the running job.

Subsequent browser discovery exposed the Chrome extension. Its live tab list
shows the OnDemand file page redirected to `login.case.edu/cas/login`; claiming
the existing shell tab timed out. A request to the user to restore CWRU login
is pending. Local engineering continues; do not treat stale native app screen
snapshots as fresh scheduler observations. The failed log-read attempt and
browser timeout are preserved as unavailable evidence, with no new job.

## Next actions

1. Continue the document reading inventory; long historical material is
   indexed but not all paragraphs have been reviewed. All three known source
   PDFs have now been read in full, with selected figures/formulas checked;
   proof verification and experiment reproduction are separate. Markdown
   progress is 55 full / 8 selected sections / 18 detailed reviews pending.
2. Observe 3796988 completion and its coverage gains/losses using bounded
   read-only logs/artifacts. Do not equate scheduler completion with success.
3. Prepare the independent result-verification/admission gate for the new
   materialized-response contract; current replay checks only parsing/grounding
   and successful final source links. Keep the new inline bundle/spec separate.
   Establish vLLM schema compatibility and actual request fit with the existing
   bounded probes after selecting the catalog from CPU evidence. Do not launch
   another GPU experiment or change the active server checkout prematurely.
4. Prepare a real two-engine answer admission over inference-owned data.
   Current typed-row results are not full GrailQA execution or accuracy.

## Continuation

Existing automation `xgap` was updated, not duplicated, to an hourly heartbeat
on this task. It continues one bounded engineering/experiment cycle at a time,
and stays quiet when there is no meaningful change. Local continuation needs
the computer and Codex app running. This goal remains in progress.

## Persistent rules

Never use gold to construct retrieval/deployment data. Keep all evaluation
denominators and failed records. Do not rerun the accepted FinBench campaign,
change its population, or claim independent instance-memory gains from the
recorded fixed-route tie. External failures are observations without silent
retry. Ask the user only for unavailable credentials/network/server action,
external artifacts, or a material scientific decision; routine authorized
implementation and testing continue autonomously.
