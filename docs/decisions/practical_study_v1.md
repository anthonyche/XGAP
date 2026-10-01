# Explicit strong-study cells reuse the existing supervised trial and journal

2026-09-15. The new method worker supports trusted_template, but the old48-group
campaign maps only legacy methods and one global profile. Add a separate input
freezer/one-group dispatcher, preserving all existing method lists and journals.
This is necessary experiment wiring, not activation of a paper campaign or a new
baseline algorithm. No graph/model evaluation runs in this milestone.

The caller supplies1..128 groups, each with exact request, practical profile and
post-seal reference pins. Admit both modes, freeze each distinct published profile
once and retain declared group order with alternating mode order. Require unique
question IDs, a common dataset and identical declared sources/backend clients.
The same group uses identical initial input and available profile definitions for
both modes; per-mode permissions/actions/budgets are already explicit in that
profile. Do not read reference contents or make calls during freezing. Do not
infer authority from a path/hash, create questions, rewrite old denominators or
declare this ready for paper evaluation. The old campaign CLI rejects this new
caller_owned_practical deployment instead of silently using its legacy route.

The caller owns live serving handles and closes them after dispatch. The new
dispatcher reuses dispatch_one_group, run_practical_trial and score_trial. Only
client URLs and separately recorded offline deployment provenance may change
between the frozen and serving profile; every source URL must point through the
supplied owned observer. Reference pins are withheld from readiness/deployment
callbacks and method arguments. The scorer reads them only after a sealed method
result. Score failure is recorded separately and never triggers method rerun.

Durable intents are never reexecuted, including indeterminate ones. A failed
method requiring source retirement stops the remaining group cells in that call;
a later call may use a new owned serving session and continue only unrun cells.
Endpoint-validation/preparation and study dispatch time are recorded as an outer
layer around common method time, not hidden as free per-query work. Offline store
startup remains caller-owned and separately accounted. Existing wall/RSS/source
guards stay in the common boundary. No source ownership is reclaimed by PID.

Acceptance: six focused input/dispatch cases, no live services. Preserve frozen
profiles/populations and no-gold preparation; alternate mode order; exactly-once
resume including indeterminate intents; post-seal scoring failure without rerun;
stop after method failure; reject changed mode settings or unobserved endpoints;
reject duplicate IDs. Existing core/common-native gates remain their own evidence.

The paper-specific partial-binding population, mode parameters, external common
frontend contract and final release manifest remain to be frozen. This adapter
does not invent those decisions or claim that the new study has been evaluated.
