# Complete strong policy before optional terminal refinement

2026-09-15. The15ms/three-outcome counterexample in the
[information-cost report](../report/practical_information_cost_20260915.md) shows
that finishing each leaf's optimization before its siblings can lose an otherwise
available whole-policy seed. This milestone fixes the feasible-first algorithm,
not the discrepancy contract, baseline, physical candidate domain or estimator.

## Algorithm and invariants

For each visited state retain one lazy terminal iterator capped at T candidates.
Consume only until its first resource-feasible terminal. If no terminal is found,
complete an acquisition action's entire declared outcome set as before. Do not
resume any optional terminal suffix until that root candidate is fully strong.
Record the first complete root policy before optional work.

Once complete, refine its leaves in stable outcome order with the saved iterators,
remaining time and the original per-path resource reservations. The terminal cap
counts initial admission and refinement together; never recreate a stream to
reset it. Recompute acquisition-plus-worst-child scores bottom-up. Replace a leaf
only with a better admitted estimate (known before unknown, then numeric cost).
After refinement, consider further root actions within the original action budget.
Every candidate being refined is already strong; expiry or an optional-generation
exception keeps its best complete version. Unexpected exceptions before a feasible
root retain the previous error behavior. Optional errors are recorded explicitly.

A path's information resources plus its new terminal resources must fit; no budget
is reset per outcome. Unknown estimates stay null. Nonnegative known estimates
give nonincreasing returned-policy scores under accepted leaf refinements; there
is no actual-latency, global-optimality, search-completeness or approximation bound.
Strongness follows from complete-AND induction; optional replacement changes only
an already feasible terminal and cannot remove an outcome.

S/A/O/H/T caps remain global. At most S*T terminal values are consumed across
both phases. Saved iterator/usage records use O(S) entries plus their polynomial
domain state. A conservative total bound adds O(A*S) policy traversal/backup to
the existing O(S*T*C(n) + S*M*O*n + A*O*n) local-domain bound. Finite depth alone
is still insufficient. Atomic compilation/prediction may exceed a soft deadline.

Practical-domain caches must distinguish a yielded seed from completed optional
work: another stream may resume that binding's one optional construction. All
streams then reuse the cached result, without treating a partial cache as a
completed optimization or recomputing it. Domain calls stay symbolic and local.

## Scope and acceptance

Allowed: strong_planning, practical terminal cache, focused tests, one affected
in-process vertical slice and a bounded offline real-input check. Forbidden:
source/model calls, new dataset execution, changed estimator/profile weights,
baseline algorithms/order, altered semantic outcomes or hidden retries.

Check the saved deadline counterexample, a budget allowing refinement, pathwise
resource rejection, terminal caps spanning phases, optional exceptions, unresolved
AND outcomes, interleaved cache streams and the real in-process authority-to-query
path. Because the generic solver changes, run its small existing eight-case suite
and only the affected practical deadline checks, not the full repository suite.

RQ: can optional optimization preserve timely strong-plan availability?
X: remaining budget and terminal refinement cost. Y: first full-policy time,
availability, final estimate, consumed candidates and actual final-plan count.
MaterialPassport: algorithm correction and bounded development evidence.
