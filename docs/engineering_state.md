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

D196 / H2: preserve RDF term and resource identity through explicitly selected
native compilation, HTTP execution, runtime fragment wiring, and answer projection.
Implementation and 153 focused tests pass (one live gate skipped).
Full regression: **2503 passed, 37 skipped in 604.92 seconds**.
The harness check and all 19 acceptance examples also pass.
The new live Fuseki test is explicitly gated and not yet measured.

Full regression log: `/tmp/xgap-review-20260909/full-regression.log`.
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
   indexed but not all paragraphs have been reviewed. See review report.
2. Observe 3796988 completion and its coverage gains/losses using bounded
   read-only logs/artifacts. Do not equate scheduler completion with success.
3. Make H3 a separately versioned interpretation-sketch interface with
   deterministic mechanical references, preserving strict semantic validation.
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
