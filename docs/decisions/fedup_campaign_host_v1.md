# Frozen author summary and campaign method hosts

Milestone: connect the original FedUP/FedX hosts to the accepted disk-backed RDF
sources and per-request observer. This closes formal evaluation prerequisites;
it does not improve a baseline algorithm or repair its answers. Only experiment
preparation/host/controller code and new boundary tests are in scope. Existing
models, queries, catalog, population, baseline JARs and original failures stay fixed.

Build FedUP's summary offline once from the exact graph/control RDF input hashes.
Use named graphs `http://xgap-source.invalid/graph/sparql` and
`http://xgap-source.invalid/control/sparql`; these are logical identities only.
The original CLI `--modify` maps this common prefix to the current observed
loopback base URL. The author's server and ASK/source-selection paths already
implement this option. No query-dependent mapping or network access to `.invalid`.
Frozen summary files are copied for serving, never rebuilt after each question.

Use the pinned author server/summarizer JARs and existing hash modulo1 profile.
Two native TDB named-graph loads: one attempt each,2GiB heap/3GiB sampled RSS/900s.
One author summarizer invocation:4GiB heap/6GiB sampled RSS/900s, chosen before
any result because the original CLI materializes per-graph triple/quad lists.
All are offline costs, separate from the common online2GiB method/source budgets.
Keep the10GiB output/6GiB free-disk guard and all partial failures. Do not replace
the author summarizer with an optimized implementation or retry a failed run.

Host initialization has its own sealed observer phase; source requests during
initialization are accounted separately. Per-request failures still retire all
owned services; the next distinct cell gets a new session. Healthy method hosts
may retain their native caches. Idle hosts are outside the active method's RSS,
but total machine/package memory must remain feasible. Frozen host settings use
original FedUP with engine FedX and the already pinned matched FedX adapter.

Acceptance: prepare the new logical-source summary on the already accepted tiny
RDF inputs and issue one SELECT through each newly integrated host. Compare the
plain account business-ID rows to independent tiny facts; validate observation
seals and source routing, preserve any native failure, then stop owned services.
Do not rerun the previously censored generated FedX question, the FedUP aggregate
failure, or successful one-shot NL/planning gates. No live LLM call is needed.
If this boundary works, prepare the same summary recipe once on frozen SF0.1.

## Package dispatch boundary

Actual controller integrates the frozen schedule and one-attempt journal. Each CLI
chunk admits at most1..4query groups (at most16method cells),3600s package time,
12GiB sampled package disk and6GiB free-disk reserve. Admission additionally reserves
300s and2GiB for a complete cell/setup. These are finite sampled resource limits,
not strict OS bounds; in-flight writes may overshoot a sample. The package monitor
also runs inside the existing owned-resource watchdog, so disk/time pressure can
terminate the current method without allowing an unbounded write. Models remain
at most one generation per NL cell, capped at the existing6144output tokens and
frozen request-byte/token guard; no dollar cost is invented. Fixed track calls no LLM.

A package advisory file lock serializes controllers. Campaign identity pins the
schedule, prepared sources, summary and implementation tree; documentation commits
do not change implementation identity. Canonical fixed requests are derived once
per question from the frozen gold; all methods receive the same fixed query input.
The NL path never opens gold. References remain a post-outcome scoring input.

Healthy sessions/hosts persist within a chunk. Failed cells stop active method and
sources, then retire all other owned hosts before the next distinct cell gets a new
session. Startup/replacement preparation is separately recorded; required extra
retirement time augments the common online boundary. Declared chunk boundaries
start fresh sessions on resume, with no warmup. All outputs, errors and partial
ledger records persist. Only new reconstructable serving copies of already sealed
stores/summary are discarded after all owned groups drain; original artifacts,
logs, query responses and receipts are retained. No historic files are deleted.

New focused acceptance: package admission does not abort its last admitted cell;
package failure reaches the owned worker watchdog; actual controller preserves a
healthy session, replaces a failed one, keeps identical fixed input across methods
and does not read NL gold. After these and the new real host boundary, dispatch the
first frozen fixed-semantics evaluation group once. This begins the approved real
evaluation, not development debugging on a large dataset.

## First real group and transport correction epoch

The first group remains immutable: XGAP returned the correct empty answer in53.112s
(planning23ms, execution45.248s,112.486MB source responses); FedX encountered local
EADDRNOTAVAIL after8198 observed requests; subsequent retirement raised PermissionError
and left the dead session attached, so FedUP never submitted its method query.
This is not evidence of native baseline inferiority. The original retirement stack
was not captured, so its precise operation is unknown. The state-retention defect
is independently replayed and fixed without reproducing the full-data failure.

The campaign observer now uses HTTP/1.1 and retains at most16 idle upstream
connections per source for1second; it neither caches responses nor retries stale
connections. This removes transport-forced connection churn. Active method request
semantics, native batching and query count are unchanged. Every logical request
still has its own ledger; new/reused upstream connection counters are explicit.
Local address/file-descriptor exhaustion is classified as harness transport resource
failure. The legacy observer keeps its old HTTP/1.0 default.

Cleanup detaches the session before any fallible operation and halts dispatch if
quiescence or retirement recording is uncertain. Canonical outcomes already sealed
remain scoreable even if later controller cleanup fails. New focused replay checks:
20 HTTP calls use1 upstream connection, stale connection fails without retry,
saved PermissionError prevents reuse, and an append-only correction epoch cannot
change input pins or redispatch prior intents. The first three checks pass0.55s;
the epoch check passes0.33s. No baseline or full-data query was rerun for this fix.

An explicit documented harness epoch may change implementation only while preserving
schedule/source/summary pins, all prior intents and outcomes. It is append-only;
future dispatch skips the three original cells. Disclose epochs and do not silently
pool their timing. This is an integration correction, not a new workload, altered
baseline or retry to replace the first result.

The next four-group chunk sealed8new outcomes and halted before a9th cell when
retirement failed again. Its stack now identifies the legacy tiny
`Processes.stop` blind killpg call. The affected Java leader was verified zombie
with matching creation identity; other owned services were absent. The completed
controller still waited on its observer thread, so its exact PID/creation/cmdline
was checked and only that controller was sent SIGTERM; the exec handle then
confirmed exit143. No query was restarted and the next cell remained unrun.

Campaign closure now drains each owned group using the guarded primitive instead
of the legacy helper, reaps leaders, closes the observer, then discards only new
serving copies. A PermissionError between scan and signal is resolved only by a
new read proving no live group members; genuine live permission denial still
propagates. Two new race checks pass0.35s; a new owned-child/copy-retention check
separately verifies the campaign close path. This adds another disclosed harness
epoch; none of the first14cell intents may be redispatched. Resume first at the
previously unrun FedX cell in group4, retaining all first outcomes and code epochs.
