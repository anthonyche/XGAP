# M4.5 Semantic Audit

## Scope

This audit checks the implemented XGAP logical algebra after M4 against the documented path-algebra semantics, type-flow invariants, examples, and tests.

Audited operators:

- `Nodes(G)`
- `Edges(G)`
- `Selection`
- `Union`
- `Join`
- `Recursive`
- `GroupBy`
- `OrderBy`
- `Projection`

No future milestone behavior was implemented during this audit.

## Audited Invariants

Type flow:

- `Nodes(G) -> PathSet`
- `Edges(G) -> PathSet`
- `Selection(PathSet) -> PathSet`
- `Union(PathSet, PathSet) -> PathSet`
- `Join(PathSet, PathSet) -> PathSet`
- `Recursive(PathSet) -> PathSet`
- `GroupBy(PathSet) -> SolutionSpace`
- `OrderBy(SolutionSpace) -> SolutionSpace`
- `Projection(SolutionSpace) -> PathSet`

Core path algebra:

- `Nodes(G)` returns exactly zero-length node paths.
- `Edges(G)` returns exactly one-length edge paths.
- `Selection` only filters existing paths.
- `Union` is deduplicating, idempotent, and commutative.
- `Join` concatenates only compatible paths and removes the duplicated middle node.

Recursive path algebra:

- `WALK` requires positive `max_depth` and permits repeated nodes and edges.
- `TRAIL` rejects repeated edges.
- `ACYCLIC` rejects repeated nodes.
- `SIMPLE` permits only a closing repeat where first node equals last node.
- `SHORTEST` returns minimum-length paths per source-target pair and keeps tied shortest paths.
- `Recursive` is Kleene-plus, not Kleene-star.
- Kleene-star remains expressible as `Union(NodesOp(), RecursiveOp(...))`.

SolutionSpace algebra:

- `GroupBy` preserves exactly the input paths.
- Each path maps to exactly one group.
- Each group maps to exactly one partition.
- Path, group, and partition ranks are positive.
- `GroupBy` initializes all ranks to 1.
- Empty `PathSet` produces empty `SolutionSpace`.
- All grouping keys were audited: `NONE`, `SOURCE`, `TARGET`, `LENGTH`, `SOURCE_TARGET`, `SOURCE_LENGTH`, `TARGET_LENGTH`, `SOURCE_TARGET_LENGTH`.

Ordering and projection:

- `OrderBy` preserves paths, partitions, groups, and assignments.
- `OrderBy(PATH)` sets path ranks to path lengths.
- `OrderBy(GROUP)` sets group ranks to minimum group path length.
- `OrderBy(PARTITION)` sets partition ranks to minimum partition path length.
- Combined order keys update only the intended rank levels.
- `Projection(None, None, None)` returns all paths.
- `Projection(None, None, 1)` returns at most one path per group.
- `Projection(None, 1, None)` returns paths from at most one group per partition.
- `Projection(1, None, None)` returns paths from one partition.
- Projection output is always a subset of the input solution-space paths.
- Projection tie-breaking is deterministic.
- Zero and negative projection limits are invalid.

## Selector Mapping

| Selector style | Logical plan shape |
| --- | --- |
| ANY | `Projection(*, *, 1) -> GroupBy(SOURCE_TARGET) -> Recursive(...)` |
| ANY k | `Projection(*, *, k) -> GroupBy(SOURCE_TARGET) -> Recursive(...)` |
| ANY SHORTEST | `Projection(*, *, 1) -> OrderBy(PATH) -> GroupBy(SOURCE_TARGET) -> Recursive(...)` |
| ALL SHORTEST | `Projection(*, 1, *) -> OrderBy(GROUP) -> GroupBy(SOURCE_TARGET_LENGTH) -> Recursive(...)` |
| SHORTEST k | `Projection(*, *, k) -> OrderBy(PATH) -> GroupBy(SOURCE_TARGET) -> Recursive(...)` |
| SHORTEST k GROUP | `Projection(*, k, *) -> OrderBy(GROUP) -> GroupBy(SOURCE_TARGET_LENGTH) -> Recursive(...)` |

## Paper-Style Examples

The audit uses the Knows graph:

```text
n1 -e1:Knows-> n2
n2 -e2:Knows-> n3
n3 -e3:Knows-> n2
n2 -e4:Knows-> n4
```

Audited plans:

- ANY SHORTEST TRAIL:
  `Projection(*, *, 1) -> OrderBy(PATH) -> GroupBy(SOURCE_TARGET) -> Recursive(TRAIL) -> Selection(label(edge(1)) = "Knows") -> Edges`
- ALL SHORTEST ACYCLIC:
  `Projection(*, 1, *) -> OrderBy(GROUP) -> GroupBy(SOURCE_TARGET_LENGTH) -> Recursive(ACYCLIC) -> Selection(label(edge(1)) = "Knows") -> Edges`

## Known Implementation Choices

- Deterministic tie-breaking is used for nondeterministic selector styles.
- `None` represents `*` in `Projection`.
- Empty `PathSet` produces an empty `SolutionSpace` with no synthetic partition or group.
- `WALK` requires explicit positive `max_depth`.
- `Recursive` is Kleene-plus; Kleene-star is modeled by unioning with `Nodes(G)`.

## Known Limitations

- Pattern lowering remains unimplemented.
- Backend capability profiles remain unimplemented.
- GQL, Cypher, and SPARQL compilers remain unimplemented.
- Logical optimizer rules remain unimplemented.
- LLM planning, disambiguation, learned cost estimation, and KGQA evaluation remain future milestones.
- The in-memory evaluator is a reference evaluator, not a backend execution engine.

## Commands Run

```bash
python -m pytest tests/test_semantic_audit.py -q
python -m pytest -q
python examples/semantic_audit_demo.py
./scripts/run_acceptance.sh
```

## Result Summary

The semantic audit passed. No implementation bug was found or fixed during M4.5. The audit added dedicated semantic tests, a semantic audit demo, and this report.
