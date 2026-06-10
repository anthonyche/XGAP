cat > AGENTS.md <<'EOF'
# XGAP Agent Harness

## Project identity

You are working on XGAP, an ambiguity-aware natural-language-to-graph-query planner.

XGAP's logical planning layer must align with the path algebra from the paper "Path-based Algebraic Foundations of Graph Query Languages".

The full pipeline is:

Natural language question
  -> candidate path-pattern query
  -> deterministic lowering to path-algebra logical plan
  -> logical optimization
  -> compilation to target query languages: GQL, Cypher, SPARQL
  -> optional backend execution and evaluation

## Required reading before every task

Before changing code, read these files:

1. docs/architecture.md
2. docs/roadmap.md
3. docs/status.md
4. docs/operator_semantics.md
5. docs/decisions.md, if it exists
6. The sprint prompt under prompts/sprints/, if provided

After reading them, briefly state:
- current milestone
- allowed files to modify
- forbidden changes
- acceptance criteria

## Core algebra invariants

The logical algebra must only use:

- Nodes(G)
- Edges(G)
- Selection
- Union
- Join
- Recursive with modes WALK, TRAIL, ACYCLIC, SIMPLE, SHORTEST
- GroupBy
- OrderBy
- Projection

Do not introduce other logical operator names such as:

- NodeScan
- EntityLookup
- EdgeExpand
- PathExpand
- Filter
- Aggregate
- Rank
- Project

Entity grounding belongs outside the logical algebra.

The primary data object is PathSet.
The secondary data object is SolutionSpace, used only for selector-style operations.

## Scope

The MVP supports path-centric graph queries and regular path queries.

Do not claim or implement arbitrary conjunctive graph pattern matching in the core algebra unless a future milestone explicitly adds it.

## Implementation rules

- Python 3.11+
- Use dataclasses and type hints.
- Keep modules small and testable.
- Use pytest.
- Do not introduce heavy dependencies in the algebra core.
- Do not rely on an LLM for deterministic lowering, validation, or evaluation.
- Unimplemented future features must raise NotImplementedError.
- Never silently return empty results for unimplemented behavior.
- Do not implement future milestones unless explicitly asked.

## Work protocol

For every sprint:

1. Read the required project docs.
2. Inspect the relevant source and tests.
3. Produce a short implementation plan.
4. Implement only the current milestone.
5. Add or update tests.
6. Run pytest.
7. Run examples if the sprint requires them.
8. Update docs/status.md.
9. Report changed files, tests, commands run, results, and limitations.

## Definition of done

A milestone is DONE only if:

- implemented behavior matches docs/operator_semantics.md
- pytest passes
- required examples run
- docs/status.md is updated
- no future feature is faked
- no unrelated refactor is introduced
EOF