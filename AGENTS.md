# XGAP research prototype — current engineering authority

Current entry: `xgap.api.answer`; active contract:
`docs/decisions/bounded_joint_system_v1.md` (T4, 2026-09-17).
Read `docs/goal.md`, `docs/status.md`, `docs/architecture.md`,
`docs/implementation_chapter6.md`, `docs/operator_semantics.md`, and the relevant
linked decision before changes. Read `docs/roadmap.md` for next actions.

The user authorizes legacy cleanup, compressed evidence, bounded NL candidate
construction, authoritative simulated-user scope/clarification, joint end-to-end
cost planning, focused toy/native verification and GitHub synchronization.
2026-09-20 T6 supersedes the evaluation hold: the user approved execution of
`docs/research_experiment_plan_20260920.md` after reasonableness review. Follow
`docs/decisions/chapter7_execution_v1.md`: intake/log gates, development pilot,
frozen release, then the same E1–E20 matrix on three derived datasets. Preserve
missing capabilities explicitly; never invent measurements to fill a figure.
Do not restart T3, run broad regression sweeps, or optimize baseline algorithms.
Historical instructions are evidence, not work.

2026-09-20 T5 authorization: wire the current worker into common batch dispatch,
compressed-answer scoring, budgets and nonduplicating resume while the user designs
Chapter 7. See `docs/decisions/bounded_joint_batch_v1.md`. This does not authorize
full evaluation or revival of historical campaigns; T6 now authorizes new planned
evaluation releases after its readiness and resource gates.

## Invariants

- Preserve audited algebra and compiler semantics. No invented low-level operators.
- Model/catalog output proposes; it cannot attest user intent or scope completeness.
- The private simulated user may hold the true query. Only paid tool replies may
  affect online decisions. Do not expose private intent/reference rows to a model.
- Fixed fields and hard coordinates cannot be relaxed. Performance's certificate
  bounds declared structured-intent discrepancy, not answer F1 or open-NL error.
- Both modes share candidates, sources, tools and budgets. Check terminal first;
  selected information actions require a feasible continuation for every outcome.
- Retain a feasible incumbent under optional search limits. PTime claims need
  explicit finite input/compilation bounds. No global optimum/approximation claim.
- Use frozen estimates/ranks; no current-query trial executions to select a plan.
- Execute at most one final federated plan. Record real calls/tokens/bytes separately
  from declared cost units and offline preparation; unknown is not zero.
- Keep credentials out of files/logs/Git. Preserve old commits, frozen artifacts,
  failed trials and jobs. Never retry/cancel/switch an old job without authority.
- Baselines run faithfully; no result-driven changes. Old entry shims stay for
  reproducibility. Shared runtime/compiler modules are not disposable legacy.
- Test changed contracts on portable toy data plus a necessary real tiny boundary.
  Do not make expensive GrailQA preprocessing the development loop.

Historical harness: `docs/agent_harness_history_20260917.md`.
