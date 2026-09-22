# XGAP research prototype — current engineering authority

2026-09-22: current authority is `docs/ch6_experiment_plan_20260922.md`,
`docs/query_structure_spec_20260922.md`, and `docs/coding_agent_brief_20260922.md`.
Inventory, builders and local development tests are authorized. Paid model,
backend interface/pilot execution and full experiments require separately frozen
execution budgets. Do not resume old automations or relabel historical results.
The user also authorized replacing D2 with a usable alternative: see
`docs/decisions/ch6_dataset_and_methods_20260922.md` (MovieLens development intake;
stable 20M proposed for evaluation, no fabricated Wikidata mappings).

Current entry: `xgap.api.answer_unified`; controlled entry:
`xgap.api.answer_unified_controlled`; contract:
`docs/decisions/unified_lookahead_migration_20260921.md`.
Read `docs/goal.md`, `docs/status.md`, `docs/architecture.md`,
`docs/implementation_chapter6.md`, `docs/operator_semantics.md`, and relevant
linked decisions before changes. Read `docs/roadmap.md` for remaining work.

The user authorizes necessary tiny development gates, legacy isolation,
compressed evidence, faithful baseline integration and GitHub synchronization.
This is a bounded research prototype. Do not expand universal NL support or
build general open-source-product features instead of advancing the experiment.

## Invariants

- One fixed-D online controller; Lambda/epsilon are validation/loss parameters.
  Do not restore separate Exact/Performance algorithms or search a full H tree.
- Preserve audited algebra/compiler semantics. No invented low-level operators.
- Model/catalog output proposes; it cannot attest intent or scope completeness.
  Only the metered authoritative user tool may disclose private intent online.
- Mandatory validation is independent of singleton candidates and zero loss.
  Fixed fields/hard coordinates never relax. The current distance is structured
  query discrepancy, not output-F1 or open-NL error.
- Before optional work, preserve a compact completion witness for EVERY outcome,
  including unknown/probability-zero outcomes. Completion-aware leaf scores are
  estimates, not resource certificates. Retain protected seeds and suppress
  repeated no-progress work. Unknown bounds are never zero.
- PTime needs fixed D and explicit candidate/action/outcome/plan/representation
  bounds, plus polynomial local operations. No global-optimum/whole-policy ratio.
- Use frozen estimates or declared work models, never current-query trial plans
  to choose a winner. Physical moves are individual checked transformations.
- Execute at most one final plan. Only selected actions enter the paid ledger;
  hypothetical work, actual calls/tokens/bytes, declared cost units and offline
  preprocessing are reported separately. No invented measurements.
- Preserve old commits, frozen/failed trials, jobs and historical method IDs.
  Do not retry/cancel/switch an existing run without authority.
- Baselines run faithfully. Fix environment/transport integration only; do not
  tune their algorithms, prompts, outputs or decoding to improve their results.
- Test changed contracts on portable toy data and necessary real tiny boundaries.
  No blanket regression/ablation campaign or GrailQA preprocessing in development.
- Keep credentials/private intent/large artifacts out of Git. Push without
  rewriting remote history. Shared compiler/runtime code is not disposable legacy.

Historical instructions: `AGENTS_history_20260921_before_unified.md` and
`docs/agent_harness_history_20260917.md`; neither is current work authorization.
