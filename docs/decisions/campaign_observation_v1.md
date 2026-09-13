# Per-request campaign observation and resource boundaries

The ordinary NL bridge now exists. The next milestone closes its experiment
control boundary, not baseline optimization: a tiny observer's256-request lifetime
cap must not silently become a formal per-query or across-query budget.

Allowed: an explicit campaign observer alongside the frozen legacy tiny observer,
common outcome classification/finalization, a versioned common budget, small tests
of the new HTTP/accounting boundary and subsequent campaign control. Do not change
baseline JARs/settings/query generation, model/estimator/catalog/population, rerun
the censored FedX question, or run large-data debugging/ablations.

The formal source observation profile is identical for every method:65,536 requests
per phase,16MiB incoming body per request,128MiB total incoming body+target bytes,
256MiB received source response per request and512MiB received response bytes per
phase;120s source I/O deadline. These are finite engineering storage/resource
ceilings, not tuned algorithm parameters or claimed approximation bounds. Each
phase is one measured request or explicitly separate initialization. The common
180s overall watchdog and2GiB method/source sampled RSS budgets remain. Source
response bytes are read in1MiB chunks; the aggregate received-byte stop can overshoot
by at most one in-flight chunk per concurrent reader. Charge actual partial bytes.
Do not claim a strict OS memory/network cap. A method result may remain unknown
under a resource cap and must be labeled as such, not intrinsic wrong semantics.

This is a new shared formal budget, not a repeat of the prior censored development
query. Final campaign manifest must pin it before dispatch. Per-dataset sources
and clients must use compatible declared time/result limits; do not inherit tiny
20s client limits by accident. The package controller must check aggregate disk
and maximum model/time budgets separately before starting evaluation.

Keep source URLs stable across normal successive cells to preserve declared native
cache state. Incoming source records receive monotonically increasing ledger IDs;
never reuse file names when resetting a query budget. Full responses stream to disk
and only compact counters/file pins remain in memory. Close/seal a drained phase,
write the method outcome, then verify that outcome's pin before releasing compact
records. A late call after sealing is recorded and prohibits session reuse. Failed
method sessions still stop all owned method/source groups; subsequent different
cells require new sessions. Never retry the failed cell or discard its first result.

The common receipt separates harness call/byte/persistence/phase failures from
upstream HTTP/network errors and method/worker resource failures. All remain in
the run ledger and denominators with explicit categories. An observer budget error
cannot be cited as a native baseline quality failure. Archived phases must remain
addressable by file pins; records are not silently forgotten when memory is released.

Acceptance: two real local-HTTP phases reset small test quotas without changing the
endpoint or reusing IDs; refused early release retains records; byte-limit failures
preserve actual partial response bytes and their artifacts; upstream failures and
late calls have distinct categories; common finalization seals before release and
classifies the previously saved256-cap observation without any new baseline call.
