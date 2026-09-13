# Common per-request process guard

Approved experiment-plan prerequisite: one-shot/core correctness is accepted;
formal comparisons require finite budgets and failures in their original denominator.
RQ/X/Y: deadline-correctness and online cost versus method/mode. This change adds
measurement/termination, not planner optimization or a baseline semantic extension.

This milestone changes the experiment-only process guard, an opt-in guarded
one-shot CLI, its versioned budget, five targeted local process checks and evidence.
No model/backend/old-gate/baseline/large-data run; one new zero-call preflight may
verify integration with the existing full serving profile. Existing APIs retain
their recorded cost boundary. Baseline adapters must use the same guard later;
their native retries/algorithms are not changed by this module.

The parent starts exactly one worker in its own POSIX session/process group and
measures observed completion. The initial budget is180s wall, sampled group RSS
2GiB, log bytes1MiB, at most64 live group processes; sampling every50ms and TERM
grace0.5s. These are frozen initial resource settings, not tuned by method results.
The supervisor sends TERM then KILL to its owned group if needed and retains raw
logs, partial worker artifacts and a terminal receipt. A leader exiting with live
descendants is not accepted as complete. No automatic retry occurs.

The wall metric includes worker startup, profile/request reads and worker result
persistence. Parent input/budget-pin validation and final supervisor receipt write
are preparation/accounting overhead outside that measured subprocess interval;
record cleanup separately. Observed completion is sampled, so deadline decisions
include common monitor overhead/overshoot. A success appearing after the deadline
is not accepted. RSS is a sampled sum, shared pages may count more than once,
short peaks may be missed, and a threshold is not a strict OS memory reservation.
No global-OS or algorithmic-complexity claim follows from the resource cap.

The scope is the method worker and descendants that stay in its process group.
Hosted databases, persistent external method servers and the remote LLM are not
included, and this guard does not kill them. A future campaign must separately
freeze/observe those service resources. Do not compare a thin HTTP client's RSS
with an entire method JVM as if they were identical scopes. Workers may not detach
new sessions; these experiment commands are pinned, not arbitrary job launchers.

Any abnormal process outcome requires an external-quiescence barrier before the
next query: worker death does not establish that a remote query/model stopped.
The campaign must settle/cancel or explicitly reset its owned services and record
recovery costs. That campaign integration remains a separate gate; never clear
the barrier merely because an HTTP client disappeared. Cleanup/monitor failures
are preserved as failures, not scored fast successes.

The guarded XGAP adapter retains question/dataset/population identity even if the
child dies during profile preparation. It preserves the child's successful or
failed raw receipt when available and writes a separate normalized parent receipt
accepted by the existing post-seal scorer. Timeout/failed execution against empty
gold must score0. Interrupted usage stays unknown unless a complete child receipt
establishes it; original partial provider/backend files are retained for evidence,
not replayed online or rewritten into zero cost. Supplied credentials stay in the
inherited process environment, never in the saved environment/command arguments.

Formal campaign readiness is still false until common external input/scoring,
source-observation/service quiescence and actual full-data service loading are
connected. This guard by itself proves neither SOTA effectiveness nor speedup.

## Local acceptance

All five new process checks passed first run in0.82s with real local subprocesses:
normal/nonzero exit,180s-contract behavior at a short test deadline including
TERM-ignoring descendants, sampled RSS/log limit failures, orphan/monitor failure
cleanup, and interrupted request identity scoring0 against an empty reference.
An unrelated owned test service remains untouched by group termination. No model,
database, baseline, old regression or accepted native gate ran. Next is one
zero-network preflight using the already frozen full serving profile.
