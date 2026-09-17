# XGAP Agent Harness

Latest user authority (Sep17, T3): the user fully approved the proposed next
milestone. Implement only the two simple information-policy controls, freeze
16 new reference-stratified intent tasks, and execute the bounded SF0.1 study
in `docs/decisions/family_policy_study_v1.md`. The machine-readable protocol fixes
96 first-pass cells plus16 timing repeats, identical strong admission/tools,
two epsilon levels, no outcome-driven changes and no retry of failed cells.
This authorization supersedes older no-campaign statements only for T3. No
open-NL, model-saving or SOTA claim follows from the finite-family track.

## Project identity

XGAP is a cost-aware agentic federated graph-query system over heterogeneous
black-box graph engines. It jointly plans information-acquisition actions and
federated execution actions for partially bound semantic graph programs.

Cross-platform execution is the environment. Ontologies, catalogs, LLMs, and
user clarification are optional tools rather than prerequisites for the
deterministic execution core.

## Required reading before every task

Before changing code, read:

0. `docs/goal.md` — current user-directed priorities; its toy-first addendum
   supersedes conflicting historical development priorities
1. `docs/agentic_architecture.md`
2. `docs/m15_agentic_federated_core.md`
3. `docs/architecture.md`
4. `docs/roadmap.md`
5. `docs/status.md`
6. `docs/operator_semantics.md`
7. `docs/decisions.md` — current index, then the relevant linked decisions
8. the sprint prompt under `prompts/sprints/`, if one is provided

Then state the current milestone, allowed files, forbidden changes, and
acceptance criteria.

## Layer invariants

Keep these layers distinct:

- `xgap.semantic`: backend-independent semantic query/dataflow DAGs and holes;
- `xgap.agent`: goals, observations, policies, memory, and bounded control;
- `xgap.tools`: typed effects and pluggable external/backend interfaces;
- `xgap.runtime`: federated fragments, scheduling, exchange, coordinator work;
- `xgap.algebra`: the existing audited path and focused-binding semantics.

The semantic and control vocabularies do not rename or redefine the path
algebra. Existing algebra operators remain:

- `Nodes(G)`
- `Edges(G)`
- `Selection`
- `Union`
- `Join`
- `Recursive` with `WALK`, `TRAIL`, `ACYCLIC`, `SIMPLE`, and `SHORTEST`
- `GroupBy`
- `OrderBy`
- `Projection`

The existing focused-binding operators also retain their audited semantics.
Do not add a lower-level algebra operator without a separate semantic design
decision, reference-evaluator behavior, validation, and tests.

`PathPatternQuery` is a reusable path sub-IR, commonly carried by semantic
`Traverse`; it is not the entire interpretation or agent plan.

## Current user-approved profile (2026-09-14)

Follow `docs/decisions/practical_strong_planning_v1.md` and
`docs/practical_planning_20260914.md`: finite-depth AND/OR strong policies,
feasible-plan retention before bounded estimated improvement, no global optimum
claim. Sep16 update: the user explicitly authorizes proposing a discrepancy
definition. The opt-in finite-family contract is documented in
`docs/decisions/finite_intent_discrepancy_v1.md`; it does not provide an
answer-error or open-NL guarantee. All selected acquisition outcomes need feasible
continuations; runtime follows one and executes one final federated plan.

The bounded trusted-template core, live information/native slice, frozen profiles,
common worker and independent study exist. The first frozen evaluation at 5d82b6f
has 384/384 sealed/scored cells and all owned sessions closed; see
`docs/report/partial_strong_first_pass_20260915.md`. This does not establish open-NL
accuracy, mode-mechanism superiority, comparable SOTA efficiency, or scalability.
Legacy domains and baseline algorithms retain their behavior.

Prior user direction (Sep16): explicitly resume M0 simulated-user integration
and M1 small-graph memory/execution repairs. Implementation, focused tests and
one relevant live tiny gate are authorized. Follow the bounded acceptance in
`docs/research_next_stage_plan_20260916.md`. M2-M4 campaigns, baseline changes,
large datasets, blanket regressions and automatic wakeups remain out of this
turn's scope. Overall Goal is unfinished.

M0 integration and the M1 tiny-memory substage are verified; see
`docs/report/simulated_user_memory_20260916.md`. New direction: FIRST audit Exact
trace prefixes for terminal opportunity, before any broad search redesign.
Keep epsilon eligibility unknown without an executable certificate. Account for
avoidable acquisition and coverage as well as end-to-end cost; never credit the
necessary final plan/execution as automatically saved. A later unified search
should be terminal-first and lazy with equal permissions/caches/snapshots. If no
nontrivial cost-discrepancy-coverage frontier exists, report it; do not tune wins.

T1 now has a deterministic worst-case structured-intent certificate, scoped
private family user and terminal-first toy compiler/runtime entry. It is an
opt-in finite-family fallback, not replacement of the shared AND/OR/NL entry.
Full-intent acquisition must remain an available consideration in subsequent
information-policy comparisons; do not manufacture a win by forcing only Exact
to ask one coordinate at a time. See `docs/report/intent_terminal_20260916.md`.

Latest Sep17 direction explicitly authorizes completing the wiring and testing
real Performance tradeoffs. T2 now connects the public finite-family certificate
to the main NL API, common worker and shared strong solver, with identical
full/scoped clarification permissions. See
`docs/decisions/family_strong_terminal_v1.md` and
`docs/report/strong_intent_20260917.md`: 52 distinct targeted tests and two live
model/native executions passed; owned services are closed. Open-NL coverage,
joint lazy model/probe actions and broader evaluation remain unfinished. Do not
claim saved model calls from the optional common proposal, treat toy timing as
statistically established, or run a large campaign without its frozen plan.

The opt-in model-structure contract remains conditional and supplies no intent
authority; see `docs/decisions/nl_conditional_strong_v1.md`. Trusted-template
defaults, authority invariants and prior artifacts remain unchanged. No outcome
tuning, baseline optimization or blanket regressions.

Corrected user requirement: unattended EXACT must have a queryable simulated
user that owns authoritative intent. The real user must not answer or validate
each question. Ground-truth semantic intent may live privately in this oracle;
XGAP acquires scoped authoritative answers through explicit, metered interaction.
Do not fail merely because the real user is absent, or forbid the oracle as a
"gold fixture." Keep hidden intent out of initial method input and keep answer
rows/optimal physical plans out of intent replies. See
`docs/decisions/simulated_user_authority_v1.md`. M0/M1 implementation is now explicitly authorized.

The Sep16 NL first pass is now sealed: 12 questions, 72 method observations and
eight separately retained zero-call adapter configuration records; all owned
sessions closed. See `docs/report/nl_strong_first_pass_20260916.md`. Enter result
review; do not automatically rerun, tune, or expand this cohort. Multi-hop
intermediate work and evaluation coverage are candidates for the next toy milestone.

The previous one-shot profile below remains a versioned legacy interface.

## Previous user-approved profile (2026-09-12)

Read `docs/decisions/one_shot_modes_v1.md` and
`docs/one_shot_development_20260912.md` for the current bounded milestone.
The explicit precision/performance one-shot profile may select uncertain meanings
or truncate retrieval coverage, with provenance, without mandatory clarification.
This does not make predicted identity authoritative or relax an explicit hard
request constraint. Legacy strict APIs keep their behavior. Runtime reads frozen
catalog/statistics/estimator artifacts, selects by estimates and executes one final
plan; no default current-question candidate probing. Do not run new ablations,
comparisons or scale sweeps until the ordinary core integration is accepted.

## Agent invariants

### Baseline fidelity — user instruction, 2026-09-12

Do not optimize baseline results. Use pinned author implementations and declared
configurations. Fix only necessary environment/transport integration, without
changing their algorithms, semantic capabilities, answer logic or outcome-driven
tuning. Never add missing aggregation/order semantics, repair answers, switch
engines per query, or rerun until success to improve a baseline's score. Preserve
unsupported forms, wrong answers, failures and native internal retries with full
costs. Our adapter defects are separate from native method limitations. Do not
deliberately handicap baselines or claim a planner advantage from unsupported
semantics. The attempted FedUP outer-algebra extension is withdrawn and excluded
from evaluation; do not resume it. See `docs/decisions/baseline_fidelity_v1.md`.

- Every run starts from an explicit goal and success criteria.
- Every tool is registered, typed, and allowlisted for the goal.
- Step, tool-call, time, and resource budgets must be finite where applicable.
- Tool errors and unavailable capabilities are observations, not silent success.
- Never automatically retry a failed external action.
- Never relax a hard semantic constraint.
- Identity ambiguity may require user clarification.
- LLM calls are optional, bounded, observable, and charged to end-to-end cost.
- Remote credentials, private keys, VPN state, and Duo responses stay outside
  repository configuration and artifacts.

## Backend invariants

- Neo4j, Fuseki, and future engines are black boxes behind plugins.
- XGAP may invoke native compile, inspect, explain, profile, sample, and execute
  interfaces when the plugin declares them.
- XGAP does not claim or control backend-internal scans, indexes, joins, or
  physical optimization.
- Unsupported operations return an explicit unavailable result.
- Read-only graph queries are the default system boundary.

## Implementation rules

- Python 3.10+
- Use dataclasses, enums, protocols, and type hints for contracts.
- Keep modules small and testable.
- Use pytest and keep default tests independent of live services and GPUs.
- Do not introduce heavy dependencies into algebra, semantic, agent, or tool
  contracts.
- Deterministic validation and lowering must never depend on an LLM.
- Unimplemented features fail explicitly; never return fabricated empty data.
- Preserve existing M0-M13 experiment artifacts as a legacy baseline unless a
  milestone explicitly migrates them.

## Milestone protocol

Development is toy-first. Maintain separate Interpretation and deterministic
planning chains and an always-working tiny vertical slice. GrailQA catalog
building is explicit offline preprocessing; freeze its output and keep building
out of runtime. Use failure replay instead of repeating expensive external
failures. Module tests do not depend on GrailQA success. GrailQA-mini is a later
real-integration gate; full large datasets are for final evaluation. See
`docs/goal.md` for the user-authorized fixture chain and acceptance ladder.

For every milestone:

1. Freeze the goal, hypotheses, scope, and acceptance gates.
2. Inspect the relevant code and existing observations.
3. Implement only the current milestone.
4. Identify the research question, experimental factor, measured outcome, and
   concrete failure risk addressed by the change. Do not add work only to make
   a general-purpose open-source product more complete.
5. Select the smallest meaningful module tests and affected tiny vertical slice.
   Use saved failure replay; use live services only to verify an actual external
   boundary. Do not repeat an unchanged successful gate.
6. Run the selected checks. A broad offline suite is **not automatic at each
   milestone**: justify it by a shared-core change, unresolved regression risk,
   or the frozen experiment-release plan. Documentation-only changes need no
   software regression. This supersedes the former blanket rule, following the
   user's explicit September 11 research-directed testing instruction.
7. Update the concise current `docs/status.md`, `docs/roadmap.md`, and relevant
   design decisions. Put detailed chronological evidence in its report, not in
   repeated historical "current/next" sections. The dated history snapshots are
   read-only provenance for this workflow, not live task instructions.
8. Report changed files, commands, results, limitations, and the next gate.

## Definition of done

A milestone is done only when its acceptance behavior exists, tests pass,
required examples run, status documentation is current, and unavailable
external evidence remains explicitly unavailable. Documentation or an API
placeholder alone does not satisfy an executable milestone.

The research prototype is complete only for an explicit paper contract: supported
semantics, actual method/ablation paths, independent answers, and reproducible
cost accounting. For each planning algorithm state input size, objective,
pseudocode, polynomial time/space analysis and solution-quality guarantees with
assumptions. A timeout/candidate cap is not an approximation bound. Keep exhaustive
search as a small-instance oracle; do not present exponential placement enumeration
as the scalable planner. See `docs/research_experiment_plan_20260911.md` and
`docs/decisions/planning_ptime_contract_v1.md` before the next engineering step.
