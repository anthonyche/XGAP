# A1: one warm-snapshot refresh and pre-execution reselection

Frozen before implementation,2026-09-11, parentd66bd84. DEV mechanism gate for
R-C/E2/E3, not a new full-agent method or a change to evaluation populations.

X is the presence of one current profile observation and a subsequent placement
selection. Y is the actual action/plan difference, independent answer correctness,
current calls and total elapsed time; historical acquisition remains separate.
Use the same fully bound meaning, complete historical snapshot and backend state
in three arms: `refresh_reselect`, `refresh_only`, `no_refresh`. The first two
choose the same one registered request using prior information only. The small
acceptance input is existing B04 with a declared latency-estimate drift. This
tests mechanism wiring; a controlled drift advantage is not a real workload result.

Algorithm:

1. Admit the ordinary P1 local placement problem. Load one complete explicit
   snapshot or exact-context, unexpired memory entry. Validate all request keys
   and backend identities. Missing/expired/incomplete history fails before calls;
   these warm-only modes never silently acquire a full cold table.
2. Select the initial placement with P1. From its deduplicated remote observation
   keys choose the largest historical elapsed estimate, ties by stable key.
   This is an explicit heuristic for which one estimate to refresh, not a proven
   information-value optimum. No current measurements, answers or gold are used.
3. `no_refresh` executes the initial plan. The other arms invoke the one
   registered profile request once. On failure retain the attempt and stop;
   there is no fallback or retry. On success merge just that estimate into the
   complete snapshot with a new version.
4. `refresh_reselect` invokes P1 once more and executes its selected plan;
   `refresh_only` executes the initial plan. Report initial selection, post
   selection (null if not called), actual executed plan and its estimate under
   the most recent snapshot. Preserve each certificate's snapshot identity.

The one current acquisition and at most two P1 selections are finite. With K
local options and represented fragment size L, request selection is polynomial
in the initial plan/observation table, followed by at most two polynomial P1
runs and one final scoring pass. All P1 assumptions and model-relative bounds
remain unchanged. No global acquisition-value, actual-latency or cross-snapshot
non-regression guarantee is asserted: the coupled P1 search starts at its
prepared baseline, not the previous selected plan. Native clients retain their
configured transport timeouts; this gate adds no fictitious policy deadline or
claim of hard wall-time preemption. Remote execution is outside CPU Ptime claims.

Memory is read-only in all three arms. A partial refresh must not reset the TTL
of untouched observations or replace the original complete acquisition record.
The merged snapshot is returned in the current run only. Memory hits retain the
stored acquisition calls/time; a bare explicit snapshot has unavailable historical
cost, reported as null, never estimated from its cost table or assumed free.
Current end-to-end time includes memory lookup, both selections where applicable,
refresh, failure overhead and execution. Count every current acquisition attempt
plus actual selected-plan calls; expose inclusive refresh-stage time and its
selection/collection/other overhead without double counting.

Allowed changes: runtime refresh policy and ordinary selection/dispatch bridge,
BoundSemanticExecutionTool/frozen-query forwarding, risk-specific tests and a
tiny mechanism runner. No new algebra, native query/compiler changes, benchmark
population edits, catalog rebuild, broad regression or remote model resubmission.

Acceptance: B04 shared history selects A; a controlled current observation makes
A slower, so refresh+reselect executes B while the other arms execute A. Both
refresh arms issue the same one request, all three return the independent gold,
and read-only history/provenance remains identical. Check no-refresh, missing/
incomplete/expired history, conflicts, failed refresh, snapshot-version attribution,
and no hidden exhaustive search. Verify the normal NL/frozen-resolution path on
the tiny fixture; run a live tiny boundary only if the changed external sequence
needs validation. No repeated broad gates. Execution-prefix continuation remains
an explicit subsequent obligation requiring residual feasibility and exact node
reuse across placements; this A1 gate does not discharge it.
