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

## Agent invariants

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
