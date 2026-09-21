# Current architecture — bounded joint system v1

2026-09-21: the user has respecified the research target as unified fixed-depth
online planning. See the [migration map](decisions/unified_lookahead_migration_20260921.md).
The executable architecture below is the measured previous version; it is not
yet an implementation of the revised algorithm. Formal experiments remain paused.

The current public entry is `xgap.api.answer`. There is one system and two terminal
contracts, not two independent implementations.

```text
NL + frozen source schema
  -> compact proposal provider (model or declared deterministic grammar)
  -> finite coordinate domains -> complete bounded candidate scope
  -> paid private-user containment confirmation
  -> shared terminal-first finite AND/OR policy search
       terminal: certificate -> lazy compiler/physical neighborhood -> estimated cost
       acquisition: full/scoped user clarification -> ALL symbolic outcomes
  -> follow ONE observed policy branch
  -> execute ONE plan -> rows + certificate + cost/usage evidence
```

The first scope reply is required by both modes and does not reveal the chosen
candidate. Optional clarification reveals only requested coordinates. No private
query or gold answer is supplied to the proposal provider. Outside-scope intent is
an explicit failed attempt; it is not repaired with hidden gold.

Scope identity accepts declaration-order variable renaming and reordered pure
WHERE conjunctions; the stored queries and metric coordinates are not rewritten.
It does not claim arbitrary query equivalence or change literal/direction semantics.

T6 adds `xgap.api.answer_controlled` for the approved experiment plan: start from a
frozen full family plus authoritative public initial clues, then share the same
planner/compiler/runtime. This track excludes NL initialization from its timing.
The no-execution-feedback variant preserves physical planning; complete selected
policies and observed paths are exported separately. Independent query loss is
computed only after sealing. See the [T6 contract](decisions/chapter7_execution_v1.md).

Layers remain `semantic` (typed programs), `agent` (state/authority/policy),
`planning` (frozen costs), `runtime` (fragments/coordinator), `tools` (effects),
`compilers`/`algebra` (audited logical/native semantics), and `experiments` (recording).
GrailQA/catalog builds stay offline; no runtime dataset build is introduced.

The current batch route is `scripts/run_bounded_joint_batch.py` → common guarded
NL trial → `nl_method_worker` → `bounded_joint_worker` → `xgap.api.answer`.
The common scorer consumes sealed raw/gzip answers separately. Pinned scope,
configuration, private user and nonduplicating resume are described in the
[T5 contract](decisions/bounded_joint_batch_v1.md); reference rows never enter the worker.

See [Chapter 6 map](implementation_chapter6.md) for files, pseudocode, bounds,
semantics and evidence. [Legacy inventory](legacy_inventory.md) distinguishes
historical profiles from shared compiler/runtime components.
The [previous architecture](architecture_history_20260917.md) is retained verbatim
for historical details; its development directions are superseded.
