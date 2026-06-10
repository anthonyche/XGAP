# M5.5 Pattern-Lowering Audit

## Scope

This audit checks the M5 GPC-Lite pattern layer and deterministic lowering pipeline:

```text
PathPatternQuery
  -> type_check_path_pattern
  -> lower_path_pattern
  -> LogicalPlan
  -> validate_plan
  -> reference evaluation
```

No new functionality was added during M5.5.

## Audited Files

- `src/xgap/pattern/ast.py`
- `src/xgap/pattern/types.py`
- `src/xgap/pattern/typecheck.py`
- `src/xgap/pattern/lowering.py`
- `src/xgap/pattern/__init__.py`
- `src/xgap/algebra/ops.py`
- `src/xgap/algebra/conditions.py`
- `src/xgap/algebra/validation.py`
- `src/xgap/algebra/evaluator.py`
- `src/xgap/algebra/pretty.py`
- `tests/test_pattern_lowering_audit.py`
- `examples/pattern_lowering_audit_demo.py`

## Audited AST Classes

The implemented M5 scope includes:

- `Var`
- `PatternVarType`
- `NodePattern`
- `EdgePattern`
- `Direction`
- `Rel`
- `Seq`
- `Alt`
- `Plus`
- `Star`
- `OptionalExpr` as an unsupported lowering placeholder
- `Bounded` as an unsupported lowering placeholder
- `Selector`
- `PathPatternQuery`

The audit verifies invalid variable names, empty labels, empty property names, selector `k` validation, unsupported placeholder lowering, and frozen dataclass behavior.

## Audited Type-Checking Rules

The audit verifies:

- `path_var` infers `PATH`.
- Source and target node variables infer `NODE`.
- Edge variables infer `EDGE`.
- Reusing the same variable with the same type is accepted.
- Reusing the same variable with conflicting types is rejected.
- Repeated recursive expressions reject edge variables in M5.
- `Alt` branches must infer matching variable schemas.
- `Seq` preserves compatible shared edge variables and rejects conflicts with surrounding variables.
- `WALK` recursive expressions require positive `max_depth`.

## Audited Lowering Rules

Regex lowering remains canonical:

| Regex AST | Logical plan shape |
| --- | --- |
| `Rel(label)` | `Selection(label(edge(1)) = label) -> Edges` |
| `Rel()` | `Edges` |
| `Seq(a, b)` | `Join(lower(a), lower(b))` |
| `Alt(a, b)` | `Union(lower(a), lower(b))` |
| `Plus(a)` | `Recursive(mode, lower(a))` |
| `Star(a)` | `Union(Nodes, Recursive(mode, lower(a)))` |

The audit verifies that `Rel` conjoins label and property constraints, recursive `WALK` lowering requires positive `max_depth`, and lowered plans emit only the existing logical operators.

## Descriptor Lowering

Source descriptors lower to conditions over `first`:

```text
label(first)
first.<property>
```

Target descriptors lower to conditions over `last`:

```text
label(last)
last.<property>
```

Descriptor filters are applied before selector wrapping.

## Selector Mapping

| Selector | Logical plan shape |
| --- | --- |
| `ALL` | `Projection(*, *, *) -> GroupBy(NONE) -> base` |
| `ANY` | `Projection(*, *, 1) -> GroupBy(SOURCE_TARGET) -> base` |
| `ANY k` | `Projection(*, *, k) -> GroupBy(SOURCE_TARGET) -> base` |
| `ANY SHORTEST` | `Projection(*, *, 1) -> OrderBy(PATH) -> GroupBy(SOURCE_TARGET) -> base` |
| `ALL SHORTEST` | `Projection(*, 1, *) -> OrderBy(GROUP) -> GroupBy(SOURCE_TARGET_LENGTH) -> base` |
| `SHORTEST k` | `Projection(*, *, k) -> OrderBy(PATH) -> GroupBy(SOURCE_TARGET) -> base` |
| `SHORTEST k GROUP` | `Projection(*, k, *) -> OrderBy(GROUP) -> GroupBy(SOURCE_TARGET_LENGTH) -> base` |

The audit verifies deterministic `format_plan()` output for these selector shapes.

## Full Pipeline Checks

The audit covers complete lowering, validation, and reference evaluation for:

- `ANY SHORTEST TRAIL p = (x)-[:Knows]+->(y)`
- `ALL SHORTEST ACYCLIC p = (x)-[:Knows]+->(y)`
- `ALL TRAIL p = (x)-[:Knows]*->(y)`

The `Star` case verifies that Kleene-star remains represented as:

```text
Union
  Nodes
  Recursive
```

## Reference Evaluation Checks

The audit uses the paper-style Knows graph:

```text
n1 -e1:Knows-> n2
n2 -e2:Knows-> n3
n3 -e3:Knows-> n2
n2 -e4:Knows-> n4
```

It also uses a multi-label graph with `Likes`, `Has_creator`, and `Knows` edges.

Audited outcomes:

- `Rel("Knows")` returns only `Knows` edges.
- `Seq(Rel("Likes"), Rel("Has_creator"))` returns compatible two-step paths.
- `Alt(Rel("Knows"), Rel("Likes"))` returns paths from both labels.
- `Star(Rel("Knows"))` includes zero-length paths.
- Source descriptors filter by `first`.
- Target descriptors filter by `last`.

## Unsupported M5 Features

The following remain unsupported and fail explicitly:

- Full GPC
- Assignment semantics
- `BindingRelation`
- Query-level joins
- Conjunctive graph query semantics
- `Maybe` runtime semantics
- Group variable runtime semantics
- Aggregation over repeated variables
- Bag semantics
- Null semantics
- Reverse edge lowering
- Undirected edge lowering
- `OptionalExpr` lowering
- `Bounded` lowering
- Backend query compilation
- Backend execution
- Optimizer rewrites
- LLM planning
- Disambiguation
- Learned cost estimation
- KGQA evaluation

## Known Implementation Choices

- GPC-Lite is a structured path-pattern layer above the logical algebra.
- Lowering is deterministic and LLM-free.
- Type checking runs before full pattern lowering.
- `Direction.IN` and `Direction.UNDIRECTED` are accepted by the AST and type checker but rejected by lowering.
- Deterministic tie-breaking remains the reference evaluator's behavior for selector-style plans.
- `Recursive` is Kleene-plus; Kleene-star is represented through `Union(Nodes, Recursive(...))`.

## Commands Run

```bash
python -m pytest tests/test_pattern_lowering_audit.py -q
python examples/pattern_lowering_audit_demo.py
python -m pytest
./scripts/run_acceptance.sh
```

## Result Summary

- `tests/test_pattern_lowering_audit.py`: 33 passed.
- `python examples/pattern_lowering_audit_demo.py`: passed.
- `python -m pytest`: 188 passed.
- `./scripts/run_acceptance.sh`: passed.

No semantic implementation bug was found. No implementation files under `src/xgap/pattern` were modified.
