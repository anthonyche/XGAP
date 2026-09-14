# P-S3: deterministic progressive entity binding

2026-09-14 implementation scope: physical strategy generation, the opt-in
strong-profile domain, tiny new-risk checks and evidence. No lower algebra,
semantic/operator expansion, baseline, frozen model weights or benchmark changes.

Add at most one progressive candidate per admitted placement. Begin with the
existing complete anchor fanout when available, otherwise the coordinator plan.
Visit semantic joins by increasing DAG depth, then stable operator ID. Try the
left driver first, then right; admit at most one additional restriction per join.
Reuse canonical identity lineage, exclusive Match/Project/Filter target chains
and the existing native bind adapter. Reject a rewrite if its target is already
bound, shared, a separate answer root, unsupported or depends on its own output.
Check cycles against the accumulated candidate, not just the original plan.
Record every attempted/skipped local rewrite. Keep all original final operators.

Each admitted step is a semijoin restriction: target rows with no key in the
actual driver cannot contribute to their exclusive inner join. Preserve the
join itself, so parallel edges and repeated driver keys keep their original bag
semantics. Induction over individually equivalent, acyclic steps proves the
composed plan equivalent under the existing snapshot/identity/scalar contracts.
An empty frontier skips downstream bound calls. Overflow fails explicitly;
there is no truncation, hidden batching/retry or alternate-plan execution.

Let J be join count, L represented compiled-plan size, n semantic operators,
A in {0,1} the existing anchor candidate slot, G in {0,1} the progressive slot.
The domain per placement has at most 1+2J+A+G candidates. D admitted placements
give D*(1+2J+A+G), checked before construction. The added deterministic pass uses
O(J*(L+n)+B) conservative work after cached lineage/depth, with B generated query
bytes; it tries at most 2J directions and makes no data/model calls. It is not
join-order/subset enumeration. No approximation ratio or actual-runtime
improvement is guaranteed: extra dependencies may sacrifice useful parallelism.
The frozen estimator ranks it alongside retained alternatives; never force it
to win evaluation. Relative-ranking estimators remain allowed by the design.

Legacy strategy/one-shot interfaces default to the old domain; only the new
strong profile enables this candidate by default during optional physical
improvement. Existing baselines and serialized legacy profiles stay unchanged.
EXACT and PERFORMANCE use the same equivalence-preserving transformation; this
does not introduce a discrepancy metric or certify unvalidated interpretations.

Acceptance: independent tiny multi-hop gold including parallel edges/self-loop,
reduced later-hop source rows, empty-frontier skip, count overflow, shared-root
protection, acyclic accumulated dependencies, deterministic bound/candidate IDs,
and visibility to the new estimated domain. No full-data evaluation until this
new risk gate passes; a necessary real tiny boundary follows separately.
