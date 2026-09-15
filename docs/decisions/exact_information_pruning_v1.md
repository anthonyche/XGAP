# EXACT evidence-progress pruning

2026-09-15. The frozen partial-input development policies all put an untrusted
model proposal before the same authority action on every declared outcome.
Remove this redundancy in XGAP strong search, with unchanged input profiles,
generic AND/OR solver, PERFORMANCE and fixed-information external compositions.

## Scope and proof

This rule applies only to the concrete PracticalSemanticDomain in EXACT mode.
Its actions assign a single binding slot, optionally add authoritative evidence,
and mark their own action attempted. Available actions and their arguments/
outcomes depend on fixed declarations, validation and their own attempt flag;
they do not depend on unvalidated choices or a previous proposal response.
EXACT terminals require every slot validated. Their physical choices/estimates
depend on the final bindings and evidence, not proposal/attempt history.

Project a state onto validated choices, evidence and attempted authoritative
actions. An authority=None action leaves this projection unchanged. Authoritative
transitions commute with deleting these irrelevant proposal steps: any old
proposal value is overwritten when that slot is validated. Thus a strong policy
containing a proposal can replace that node by any one complete child policy,
recursively removing proposal nodes. It preserves terminal feasibility and every
declared outcome of all retained actions. No new outcome is invented or dropped
from a selected authoritative AND action. Model-only inputs remain infeasible.

When action/terminal estimates are known, nonnegative and functions of these
projected states, deletion cannot increase the chosen child's worst-path score
or resource reservations. With unknown scores, claim only feasible-policy
preservation and removal of the redundant calls; do not manufacture a numeric
bound. Bounded search may discover different physical candidates or hit timing
limits, so this is not a claim of identical measured latency, complete search,
global optimality, or an approximation ratio for the final heuristic solver.

Implementation filters the search view after all supplied actions, candidates,
state evidence and adapter availability have been admitted. O(M) setup for at
most128 actions; retained action generation remains within the existing polynomial
state/action/outcome bounds. All original action declarations and pruning reasons
are recorded. A selected policy still runs through the same follower once.

Do not apply this rule to general information actions that change tool sets,
query structure, hard constraints, authority domains, source health, statistics,
or later action arguments. Do not apply it to PERFORMANCE, where an unvalidated
proposal can enable a terminal. Do not change the fixed external frontend's
declared sequence or optimize author baselines.

## Development acceptance

Allowed: a small search-only view, its ordinary strong-runner integration,
targeted semantic/recorded execution tests and six affected offline EXACT inputs.
Forbidden: model/backend APIs, compilers, estimator weights, input profiles,
generic solver semantics, baseline frontend order, or successful-gate sweeps.

Check both authoritative candidate results, prevalidated state, missing authority,
declared failure continuation, unknown costs, validation before pruning and
unchanged PERFORMANCE/fixed frontend behavior. Compare the six original frozen
EXACT planning records without re-running their old code or PERFORMANCE gates.
Use a tiny recorded/in-process vertical slice; no new network boundary changed.

RQ: can semantics-aware pruning reduce information/planning work while retaining
EXACT feasibility and validated answers? X: presence of proposal-only actions;
Y: retained states/actions, root action, planning time and realized tool calls.
MaterialPassport: bounded algorithmic change and development evidence; no new
error metric, global optimum or paper-level speed/accuracy claim.
