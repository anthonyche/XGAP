# XGAP Agent Harness

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
7. `docs/decisions.md`
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

The user approved `docs/decisions/practical_strong_planning_v1.md` and
`docs/practical_planning_20260914.md`: finite-depth AND/OR strong policies,
feasible-plan retention before bounded estimated improvement, no global optimum
claim. The user will supply the discrepancy metric later; do not invent an
epsilon/answer-error guarantee. P-S1 has a working local typed/ordinary-template
slice; P-S2 added catalog/model adapters, capability lookup and one real two-engine
toy gate (see `docs/report/practical_information_native_20260914.md`). The new model
action now has one live endpoint component check. P-S3 progressive binding has
six local cases and one real two-engine component gate; source rows decreased
with unchanged gold, but measured latency advantage remains unproven. See
`docs/report/progressive_native_and_live_tools_20260914.md`. The same-request live
information + strong planning + execution gate now passes on a trusted five-node,
nine-edge template (one model372 tokens, one plan/two source queries, gold matches);
see `docs/report/practical_model_e2e_20260914.md`. Frozen mode/estimator profiles and
the ordinary publish/preflight/execute/replay entry now pass14 new+2 affected
checks; see `docs/report/practical_profile_20260914.md`. Zero new network calls,
unchanged trained weights; the development endpoints are unserved. Strict replay
checks complete original failure outcomes, not just any failure. A fixed six-cell
same-session tiny cost diagnostic now passes: second sequence coordinator145ms,
fanout169ms, progressive174ms; all gold correct, frozen rank agrees in this one
case. See `docs/report/practical_cost_diagnostic_20260914.md`. Within-plan exact
full-native sharing now passes11 new cases and one native strong request:
calls14→11, bytes18606→16399, four gold rows unchanged; no speed claim across
cold sessions. See `docs/report/shared_native_reads_20260914.md`. Necessary native
row screening now passes14 new+2 affected cases, one11-call native request
(rows64→61, bytes16399→15820, four gold unchanged), plus one Cypher type component.
See `docs/report/source_row_prefilters_20260914.md`. Next audit ordinary-profile
preparation/timing and remove repeated frozen dependency loads per request, using
focused local tests and saved replay; no new native run or cross-query answer cache.
Do not tune scores or repeat the six cells. Open-NL and superiority
remain unproven. User cutoff: Sep15 02:00 Beijing, summarize/pause until10:00.
Legacy domains default unchanged. All selected acquisition outcomes need feasible continuations. Runtime
follows one outcome and executes one final plan. The declared bounded semantic
and outcome model must be explicit; no universal plan-availability claim.

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
7. Update `docs/status.md`, `docs/roadmap.md`, and design decisions.
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
