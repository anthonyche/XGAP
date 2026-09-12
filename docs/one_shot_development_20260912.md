# Approved 48-hour core integration plan

Authority: user approval and instruction to update Goal/docs and execute,
2026-09-12, Asia/Shanghai. Start 2026-09-12 17:00; core acceptance target
2026-09-14 17:00. Real-evaluation deadline remains 2026-09-18. These are delivery
targets, not claims that performance advantages or all experiments are complete.
The [one-shot contract](decisions/one_shot_modes_v1.md) governs this work.

| Beijing time | Milestone and acceptance |
|---|---|
| Sep12 17:00–21:00 | Freeze semantics/modes/one-shot/strategy/cost contracts; update authority; begin implementations. |
| Sep12 21:00–Sep13 09:00 | Parallel bounded top-K frontdoor, real legal strategy DAGs, runtime-plan frozen estimator adapter. |
| Sep13 09:00–17:00 | Connect joint selection and one final execution to ordinary NL entry; tiny NL-to-answer slice must work. |
| Sep13 17:00–Sep14 05:00 | Actual precision/performance budgets and approximation/terminal semantics; no compulsory user loop. |
| Sep14 05:00–13:00 | Only affected module checks and necessary tiny real LLM + Neo4j/Fuseki boundary verification; preserve failed attempts. |
| Sep14 13:00–17:00 | Freeze implementation, run contract and evaluation interface; report evidence/remaining limits and discuss 16–20-figure plan. |

## Current milestone / ownership

M1 in progress. Parent checkpoint 793cc1d3e94b98bd669bd93af8346b3583c88a65.
Root owns Goal/docs, mode contract, ordinary request orchestration, joint selection
and final integration. Parallel bounded tasks own candidate interpretation,
physical-strategy compilation, and the frozen runtime estimator respectively.

Allowed: corresponding semantic/LLM/runtime/planning/agent modules, small affected
tests and current design/status documents. Forbidden: altering synced sources,
old gold, cohort IDs, exposure labels, archived outputs, secret persistence,
large-data development runs, new comparative experiments or unneeded product work.

Acceptance is staged: code exists; targeted mechanics checked; ordinary tiny E2E
checked; real external boundaries checked. Keep these states separate. Completion
requires the ordinary entry, not merely separate experiment runners or new APIs.
Targeted tests address new failure risks, not every historical milestone again.

No new expensive runs are authorized by a calendar checkpoint alone. No changes
to remote3804210; user will supply updates. External LLM availability is established.
The existing hourly development heartbeat may resume under this approved scope;
notify only meaningful progress, completion, failure or required user action.

## First execution checkpoint

The shared ordinary-entry tiny slice and initial three adapters are now implemented
and checked; see [report](report/one_shot_core_20260912.md).48 new risk cases pass,
including the two controlled modes with independent B01 answers. This advances
the ordinary-entry mechanical gate ahead of the24-hour target; actual external
LLM/Neo4j/Fuseki verification remains outstanding. Keep the dated remaining gates
and do not substitute these checks for real model or performance evidence.

## First actual native attempt

Checkpoint b008775 started and loaded both actual stores, completed four
independent tiny training measurements, and froze/reloaded the fitted estimator.
The one external B01 request returned a malformed parameter structure; binding
rejected it before planning or final execution. All four catalog resolutions
succeeded. See the retained [failure report](report/one_shot_native_20260912.md).
The real NL-to-answer gate is open; this failure is not a backend answer error.

The next change shares typed parameters between the candidate wire schema and
admission. Replay the saved failure locally and retain its original status.
The native harness now supports reuse of the accepted frozen estimator; a new
protocol gate must use it, with zero new training/fit calls. Historical training
costs remain separate from current reload and query costs. Do not repeat accepted
module gates or the four training executions.
