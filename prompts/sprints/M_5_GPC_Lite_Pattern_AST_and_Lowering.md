
## Goal

Implement XGAP's structured pattern layer and deterministic lowering from a GPC-Lite `PathPatternQuery` into audited XGAP logical operator trees.

M5 connects structured path-query intent to the audited path-algebra logical layer.

The key data-flow shape introduced in M5 is:

```text
GPC-Lite PathPatternQuery
  -> lightweight pattern type checking
  -> deterministic lowering
  -> LogicalPlan
  -> validate_plan
  -> reference evaluation
````

M5 must not implement natural-language planning, text parsing, backend compilation, backend execution, optimizer rewrite rules, learned cost estimation, disambiguation, KGQA evaluation, or full GPC conjunctive semantics.

M5 is not a full GPC implementation. It adopts only the GPC-inspired pieces needed for a path-centric structured pattern representation:

* node descriptors
* edge descriptors
* variables
* directions
* regular path expressions
* selector / restrictor information
* lightweight type checking
* deterministic lowering to existing path-algebra operators

## Required Preflight

Before implementation:

1. Read `AGENTS.md`.
2. Read `docs/architecture.md`.
3. Read `docs/roadmap.md`.
4. Read `docs/status.md`.
5. Read `docs/operator_semantics.md`.
6. Read `docs/decisions.md`.
7. Read `docs/semantic_audit.md`.
8. Inspect:

   * `src/xgap/pattern/ast.py`
   * `src/xgap/pattern/lowering.py`
   * `src/xgap/pattern/__init__.py`
   * `src/xgap/algebra/ops.py`
   * `src/xgap/algebra/conditions.py`
   * `src/xgap/algebra/validation.py`
   * `src/xgap/algebra/evaluator.py`
   * `src/xgap/algebra/pretty.py`
   * existing tests
   * existing examples

Then report:

* current milestone
* files you expect to modify
* files you will not modify
* proposed GPC-Lite AST design
* proposed type-checking rules
* proposed lowering rules
* acceptance criteria

Do not modify code before reporting the implementation plan.

## Allowed Changes

You may modify:

* `src/xgap/pattern/ast.py`
* `src/xgap/pattern/types.py`
* `src/xgap/pattern/typecheck.py`
* `src/xgap/pattern/lowering.py`
* `src/xgap/pattern/__init__.py`
* `tests/test_pattern_typecheck.py`
* `tests/test_lowering.py`
* `examples/lowering_demo.py`
* `scripts/run_acceptance.sh`
* `docs/architecture.md`
* `docs/roadmap.md`
* `docs/status.md`
* `docs/decisions.md`

You may modify `src/xgap/algebra/conditions.py` only if a tiny condition-construction helper is necessary and fully tested.

You may modify existing tests only to strengthen assertions or integrate M5 examples.

## Forbidden Changes

Do not change existing logical operator semantics.

Do not change M1-M4.5 behavior.

Do not change `RecursiveOp`, `GroupByOp`, `OrderByOp`, or `ProjectionOp` semantics.

Do not introduce new logical operators.

Do not implement full GPC.

Do not implement assignment semantics.

Do not implement `BindingRelation`.

Do not implement query-level join / conjunctive graph query semantics.

Do not implement `Maybe` semantics.

Do not implement `Group` variable semantics.

Do not implement aggregation over repeated variables.

Do not implement arithmetic conditions over group variables.

Do not implement bag semantics.

Do not implement null semantics.

Do not implement complex variable scoping.

Do not implement full GQL label expressions.

Do not implement a natural-language parser.

Do not implement GQL, Cypher, or SPARQL parsers.

Do not implement GQL, Cypher, or SPARQL compilers.

Do not add backend/database execution logic.

Do not implement optimizer rewrite rules.

Do not add learned cost estimation.

Do not add LLM logic.

Do not add disambiguation logic.

Do not add KGQA evaluation.

Do not silently fake future features.

## Conceptual Scope

M5 implements a path-centric GPC-Lite layer.

GPC informs M5 only at the structured pattern representation and type-checking layer.

M5 does not replace XGAP's audited path-algebra logical operators.

M5 does not compile to GPC.

M5 does not treat GPC as a backend language.

The intended layering is:

```text
Natural language query
  -> future LLM/grounding layer
  -> GPC-Lite PathPatternQuery
  -> type_check_path_pattern
  -> lower_path_pattern
  -> XGAP LogicalPlan
  -> validate_plan
  -> reference evaluator / future compiler
```

## Implementation Requirements

### 1. Define GPC-Lite Variable Types

Create `src/xgap/pattern/types.py`.

Implement:

```python
from enum import Enum, auto

class PatternVarType(Enum):
    NODE = auto()
    EDGE = auto()
    PATH = auto()
    GROUP = auto()   # future placeholder
    MAYBE = auto()   # future placeholder
```

`GROUP` and `MAYBE` may exist as enum values for future documentation, but M5 must not implement full semantics for them.

### 2. Define Core GPC-Lite AST in `src/xgap/pattern/ast.py`

Implement frozen dataclasses and enums.

#### Var

```python
@dataclass(frozen=True)
class Var:
    name: str
```

Validation:

* variable name must be non-empty
* variable name must be a string
* whitespace-only names are invalid

#### Direction

```python
class Direction(Enum):
    OUT = auto()
    IN = auto()
    UNDIRECTED = auto()
```

M5 type checker may accept all directions as AST values.

M5 lowering supports only `Direction.OUT`.

`Direction.IN` and `Direction.UNDIRECTED` must raise `LoweringError` during lowering.

#### NodePattern

```python
@dataclass(frozen=True)
class NodePattern:
    var: Var | None = None
    label: str | None = None
    properties: Mapping[str, object] = field(default_factory=dict)
```

Semantics:

* `var`, if present, has type `NODE`.
* `label`, if present, constrains the node label.
* `properties` are equality constraints over the node.

Validation:

* label may be `None`, but if present must be non-empty.
* property names must be non-empty strings.

#### EdgePattern

```python
@dataclass(frozen=True)
class EdgePattern:
    var: Var | None = None
    label: str | None = None
    direction: Direction = Direction.OUT
    properties: Mapping[str, object] = field(default_factory=dict)
```

Semantics:

* `var`, if present, has type `EDGE`.
* `label`, if present, constrains the edge label.
* `direction` records traversal direction.
* `properties` are equality constraints over the edge.

Validation:

* label may be `None`, but if present must be non-empty.
* property names must be non-empty strings.

M5 lowering supports only `Direction.OUT`.

#### RegexExpr

Define a base class or protocol:

```python
class RegexExpr:
    pass
```

Required regex/path-expression nodes:

```python
@dataclass(frozen=True)
class Rel(RegexExpr):
    edge: EdgePattern

@dataclass(frozen=True)
class Seq(RegexExpr):
    left: RegexExpr
    right: RegexExpr

@dataclass(frozen=True)
class Alt(RegexExpr):
    left: RegexExpr
    right: RegexExpr

@dataclass(frozen=True)
class Plus(RegexExpr):
    child: RegexExpr

@dataclass(frozen=True)
class Star(RegexExpr):
    child: RegexExpr
```

Optional future nodes may be declared but must not silently lower incorrectly:

```python
@dataclass(frozen=True)
class OptionalExpr(RegexExpr):
    child: RegexExpr

@dataclass(frozen=True)
class Bounded(RegexExpr):
    child: RegexExpr
    min_repeats: int
    max_repeats: int | None
```

If `OptionalExpr` or `Bounded` are not implemented in M5, lowering them must raise a clear `LoweringError`.

Do not use the name `Optional` for the AST node if it conflicts with `typing.Optional`.

### 3. Define Selector AST

Implement:

```python
class SelectorKind(Enum):
    ALL = auto()
    ANY = auto()
    ANY_K = auto()
    ANY_SHORTEST = auto()
    ALL_SHORTEST = auto()
    SHORTEST_K = auto()
    SHORTEST_K_GROUP = auto()

@dataclass(frozen=True)
class Selector:
    kind: SelectorKind
    k: int | None = None
```

Validation rules:

* `ANY_K` requires positive `k`.
* `SHORTEST_K` requires positive `k`.
* `SHORTEST_K_GROUP` requires positive `k`.
* `ALL`, `ANY`, `ANY_SHORTEST`, and `ALL_SHORTEST` must not require `k`.
* If `k` is provided where it is not meaningful, raise `PatternTypeError` or `LoweringError`.

### 4. Define PathPatternQuery

Implement:

```python
@dataclass(frozen=True)
class PathPatternQuery:
    path_var: Var | None
    source: NodePattern
    expr: RegexExpr
    target: NodePattern
    selector: Selector
    restrictor: PathMode
    condition: Condition | None = None
    max_depth: int | None = None
```

Semantics:

* `path_var`, if present, has type `PATH`.
* `source` describes the first node of the matched path.
* `target` describes the last node of the matched path.
* `expr` describes the edge/path expression between source and target.
* `selector` describes which matched paths are returned.
* `restrictor` selects the recursive path mode.
* `condition` is an optional existing XGAP path-level `Condition`.
* `max_depth` is used as a recursion safety bound, especially for `WALK`.

M5 does not perform entity grounding.

M5 does not implement assignment-returning semantics.

M5 does not implement multiple path clauses.

Endpoint constraints should be represented with `NodePattern.label` and `NodePattern.properties`, and lowered to existing path-level `Condition` objects over `first` and `last`.

Edge constraints should be represented with `EdgePattern.label` and `EdgePattern.properties`, and lowered to existing path-level `Condition` objects over `edge(1)`.

### 5. Implement Pattern Type Checking

Create `src/xgap/pattern/typecheck.py`.

Define:

```python
class PatternTypeError(ValueError):
    ...
```

Implement:

```python
def infer_schema(query: PathPatternQuery) -> dict[str, PatternVarType]:
    ...

def type_check_path_pattern(query: PathPatternQuery) -> dict[str, PatternVarType]:
    ...
```

Required M5 type rules:

1. `source.var`, if present, has type `NODE`.
2. `target.var`, if present, has type `NODE`.
3. `edge.var`, if present, has type `EDGE`.
4. `path_var`, if present, has type `PATH`.
5. The same variable name cannot be inferred as different types.
6. Endpoint property constraints belong to `NodePattern` only.
7. Edge property constraints belong to `EdgePattern` only.
8. M5 does not support `GROUP` variable semantics.
9. M5 does not support `MAYBE` variable semantics.
10. Repeated expressions may not contain edge variables in M5.

    * If an `EdgePattern.var` occurs under `Plus`, `Star`, `Bounded`, or `OptionalExpr`, raise `PatternTypeError`.
    * This avoids pretending that repeated edge variables are singleton edge variables.
11. `Alt` with asymmetric variable schemas is not supported in M5.

    * If `Alt(left, right)` contains variables, both branches must infer the same variable names with the same types.
    * Otherwise raise `PatternTypeError`.
    * This avoids implementing `Maybe` semantics in M5.
12. `Seq(left, right)` may share variables only if the inferred types are identical.
13. Selector `k` rules must be enforced.
14. `restrictor` must be an existing `PathMode`.
15. `max_depth`, if provided, must be positive.
16. If the regex contains `Plus` or `Star` and `restrictor == PathMode.WALK`, `max_depth` must be positive.
17. Empty labels are invalid.
18. Empty variable names are invalid.
19. Empty property names are invalid.

The type checker must not call the evaluator.

The type checker must not call an LLM.

The type checker must not lower the pattern.

### 6. Implement LoweringError

In `src/xgap/pattern/lowering.py`, define:

```python
class LoweringError(ValueError):
    ...
```

Use this for unsupported or invalid lowering constructs.

### 7. Implement Regex Lowering

Implement:

```python
def lower_regex(
    regex: RegexExpr,
    restrictor: PathMode,
    max_depth: int | None = None,
) -> AlgebraOp:
    ...
```

Required lowering rules:

#### Rel

```text
Rel(EdgePattern(label="Knows", direction=OUT))
  -> Selection(label(edge(1)) = "Knows")
       Edges
```

If `label is None` and `properties` is empty:

```text
Rel(EdgePattern(direction=OUT))
  -> Edges
```

If edge properties are present, lower them to conjunctions over `edge(1).property = value`.

If label and properties are both present, conjoin them.

Reject empty labels.

Reject `Direction.IN` and `Direction.UNDIRECTED` with `LoweringError`.

Do not introduce new logical operators for reverse or undirected traversal in M5.

#### Seq

```text
Seq(a, b)
  -> Join(lower_regex(a), lower_regex(b))
```

#### Alt

```text
Alt(a, b)
  -> Union(lower_regex(a), lower_regex(b))
```

#### Plus

```text
Plus(a)
  -> Recursive(restrictor, lower_regex(a), max_depth=max_depth)
```

If `restrictor == PathMode.WALK`, positive `max_depth` is required.

#### Star

```text
Star(a)
  -> Union(
       Nodes,
       Recursive(restrictor, lower_regex(a), max_depth=max_depth)
     )
```

If `restrictor == PathMode.WALK`, positive `max_depth` is required.

#### OptionalExpr and Bounded

If these are declared but not implemented, lowering must raise `LoweringError`.

Important:

* Lowering must emit only existing logical operators.
* Lowering must not call the evaluator.
* Lowering must not call an LLM.
* Lowering must not generate backend query strings.

### 8. Implement Descriptor Lowering

Implement helpers in `lowering.py` if useful:

```python
def lower_source_descriptor(source: NodePattern, base: AlgebraOp) -> AlgebraOp:
    ...

def lower_target_descriptor(target: NodePattern, base: AlgebraOp) -> AlgebraOp:
    ...
```

Lower source label/properties to conditions over `first`.

Examples:

```text
NodePattern(label="Person", properties={"name": "Alice"})
  -> Selection(label(first) = "Person" AND first.name = "Alice")
       base
```

Lower target label/properties to conditions over `last`.

Examples:

```text
NodePattern(label="Company")
  -> Selection(label(last) = "Company")
       base
```

Variable names do not affect lowering in M5.

Variable names are used only by the type checker and future assignment semantics.

### 9. Implement Selector Wrapping

Implement:

```python
def apply_selector(base: AlgebraOp, selector: Selector) -> AlgebraOp:
    ...
```

Selector mappings:

#### ALL

```text
Projection(*, *, *)
  GroupBy(NONE)
    base
```

#### ANY

```text
Projection(*, *, 1)
  GroupBy(SOURCE_TARGET)
    base
```

#### ANY k

```text
Projection(*, *, k)
  GroupBy(SOURCE_TARGET)
    base
```

#### ANY SHORTEST

```text
Projection(*, *, 1)
  OrderBy(PATH)
    GroupBy(SOURCE_TARGET)
      base
```

#### ALL SHORTEST

```text
Projection(*, 1, *)
  OrderBy(GROUP)
    GroupBy(SOURCE_TARGET_LENGTH)
      base
```

#### SHORTEST k

```text
Projection(*, *, k)
  OrderBy(PATH)
    GroupBy(SOURCE_TARGET)
      base
```

#### SHORTEST k GROUP

```text
Projection(*, k, *)
  OrderBy(GROUP)
    GroupBy(SOURCE_TARGET_LENGTH)
      base
```

Use `None` to represent `*` in `ProjectionOp`.

### 10. Implement Full Query Lowering

Implement:

```python
def lower_path_pattern(query: PathPatternQuery) -> AlgebraOp:
    ...
```

Lowering order:

1. Run `type_check_path_pattern(query)`.
2. Lower `query.expr` into a base `PathSet` expression.
3. Apply source descriptor constraints.
4. Apply target descriptor constraints.
5. If `query.condition is not None`, wrap with `Selection(query.condition, base)`.
6. Apply selector wrapping.
7. Validate the resulting plan with `validate_plan`.
8. Return the logical plan.

M5 must return a logical operator tree, not a backend query string.

### 11. Pretty-Print Compatibility

Lowered plans must work with existing:

```python
format_plan(plan)
```

No special pattern pretty-printer is required in M5.

### 12. Reference Evaluation Compatibility

Lowered plans must work with existing:

```python
evaluate_pathset(plan, graph)
```

M5 must include tests that:

* construct a `PathPatternQuery`
* lower it
* validate it
* evaluate it on a small graph
* compare output paths

### 13. Add `examples/lowering_demo.py`

The demo should construct the GPC-Lite equivalent of:

```text
ANY SHORTEST TRAIL p = (x)-[:Knows]+->(y)
```

as:

```python
PathPatternQuery(
    path_var=Var("p"),
    source=NodePattern(var=Var("x")),
    expr=Plus(Rel(EdgePattern(label="Knows", direction=Direction.OUT))),
    target=NodePattern(var=Var("y")),
    selector=Selector(SelectorKind.ANY_SHORTEST),
    restrictor=PathMode.TRAIL,
)
```

Then it should:

1. Lower the query.
2. Print the logical plan.
3. Validate the plan.
4. Evaluate it on the paper-style Knows graph.
5. Print output paths.

Expected formatted plan shape:

```text
Projection [*, *, 1]
  OrderBy [PATH]
    GroupBy [SOURCE_TARGET]
      Recursive [TRAIL]
        Selection [label(edge(1)) = "Knows"]
          Edges
```

### 14. Update Acceptance Script

If `examples/lowering_demo.py` exists, `scripts/run_acceptance.sh` should run it.

### 15. Update Documentation

After implementation and passing tests:

* update `docs/status.md`
* update `docs/roadmap.md`
* update `docs/architecture.md`
* update `docs/decisions.md`

Do not mark M5 DONE until acceptance passes.

Documentation must state that M5 implements a GPC-Lite path-centric structured pattern layer, not full GPC.

## Tests

Add:

* `tests/test_pattern_typecheck.py`
* `tests/test_lowering.py`

### Required Test Coverage

#### AST and Type Checking

1. `Var("")` or whitespace-only variable names are rejected.
2. `NodePattern(var=Var("x"))` infers `x: NODE`.
3. `EdgePattern(var=Var("e"))` infers `e: EDGE`.
4. `PathPatternQuery(path_var=Var("p"))` infers `p: PATH`.
5. Same variable name used as node and edge is rejected.
6. Same variable name used as path and node is rejected.
7. Empty labels are rejected.
8. Empty property names are rejected.
9. Selector `ANY_K` requires positive `k`.
10. Selector `SHORTEST_K` requires positive `k`.
11. Selector `SHORTEST_K_GROUP` requires positive `k`.
12. Selector kinds without `k` reject meaningless `k`.
13. `Plus(Rel(EdgePattern(var=Var("e"))))` is rejected in M5.
14. `Star(Rel(EdgePattern(var=Var("e"))))` is rejected in M5.
15. `Alt` with asymmetric variable schemas is rejected.
16. `Alt` with matching variable schemas is accepted.
17. `Direction.IN` is accepted by AST/type checking but rejected by lowering.
18. `Direction.UNDIRECTED` is accepted by AST/type checking but rejected by lowering.
19. `PathMode.WALK` with recursive regex and missing `max_depth` is rejected.
20. `PathMode.WALK` with positive `max_depth` is accepted.

#### Regex Lowering

21. `Rel(EdgePattern(label="Knows"))`

    * lowers to `Selection(label(edge(1)) = "Knows", EdgesOp())`
    * plan validates
    * evaluation returns only `Knows` edges

22. `Rel(EdgePattern(label=None))`

    * lowers to `EdgesOp()`
    * plan validates

23. `Rel(EdgePattern(label="Transfer", properties={"kind": "wire"}))`

    * lowers to a selection conjoining edge label and edge property

24. `Seq(Rel("Likes"), Rel("Has_creator"))`

    * lowers to `Join`
    * evaluation returns compatible two-step paths

25. `Alt(Rel("Knows"), Rel("Likes"))`

    * lowers to `Union`
    * evaluation returns both labels

26. `Plus(Rel("Knows"))`

    * lowers to `Recursive`
    * with `TRAIL`, validates and evaluates

27. `Star(Rel("Knows"))`

    * lowers to `Union(Nodes, Recursive(...))`
    * confirms Kleene-star includes zero-length paths

28. Empty relation labels are rejected.

29. Unsupported regex nodes, if present, raise `LoweringError`.

#### Descriptor Lowering

30. Source node label lowers to `label(first) = ...`.

31. Source node property lowers to `first.property = ...`.

32. Target node label lowers to `label(last) = ...`.

33. Target node property lowers to `last.property = ...`.

34. Source and target descriptors may be conjoined with regex-derived conditions.

#### Selector Lowering

35. `ALL`

    * lowers to `Projection(None, None, None) -> GroupBy(NONE) -> base`

36. `ANY`

    * lowers to `Projection(None, None, 1) -> GroupBy(SOURCE_TARGET) -> base`

37. `ANY k`

    * lowers to `Projection(None, None, k) -> GroupBy(SOURCE_TARGET) -> base`

38. `ANY SHORTEST`

    * lowers to `Projection(None, None, 1) -> OrderBy(PATH) -> GroupBy(SOURCE_TARGET) -> base`

39. `ALL SHORTEST`

    * lowers to `Projection(None, 1, None) -> OrderBy(GROUP) -> GroupBy(SOURCE_TARGET_LENGTH) -> base`

40. `SHORTEST k`

    * lowers to `Projection(None, None, k) -> OrderBy(PATH) -> GroupBy(SOURCE_TARGET) -> base`

41. `SHORTEST k GROUP`

    * lowers to `Projection(None, k, None) -> OrderBy(GROUP) -> GroupBy(SOURCE_TARGET_LENGTH) -> base`

42. Invalid selector `k` values are rejected.

#### Full Query Lowering

43. `ANY SHORTEST TRAIL` over `Plus(Rel("Knows"))`

    * lowers to the expected full plan shape
    * validates
    * evaluates on the paper-style Knows graph

44. Optional path-level condition:

    * condition wraps the lowered regex expression before selector wrapping
    * example: `first.name = "Moe"`

45. Source descriptor condition and target descriptor condition are applied before selector wrapping.

46. Lowered full plans pass `validate_plan`.

47. Lowered full plans evaluate through `evaluate_pathset`.

48. Existing M0-M4.5 tests still pass.

### Test Graphs

Reuse existing sample graphs where possible.

Add a paper-style Knows graph for M5 tests:

```text
n1 -e1:Knows-> n2
n2 -e2:Knows-> n3
n3 -e3:Knows-> n2
n2 -e4:Knows-> n4
```

Add labels/properties as needed for source/target descriptor tests.

## Run

Run:

```bash
./scripts/run_acceptance.sh
```

## Acceptance Criteria

* `pytest` passes.
* `examples/core_algebra_demo.py` runs.
* `examples/plan_print_demo.py` runs.
* `examples/recursive_demo.py` runs.
* `examples/solution_space_demo.py` runs.
* `examples/semantic_audit_demo.py` runs.
* `examples/lowering_demo.py` runs.
* `PathPatternQuery` AST is implemented.
* GPC-Lite variable/type schema inference is implemented.
* Lightweight pattern type checking is implemented.
* Regex AST lowering is implemented.
* Descriptor lowering is implemented.
* Selector wrapping is implemented.
* Lowered plans pass `validate_plan`.
* Lowered plans evaluate with the reference evaluator.
* `docs/status.md` marks M5 DONE only after tests pass.
* `docs/roadmap.md` marks M5 DONE only after tests pass.
* M6 and later remain TODO.
* No parser, compiler, backend, optimizer, LLM, disambiguation, cost-estimation, KGQA, full GPC, or BindingRelation logic is added.

## Final Report

Report:

* changed files
* implemented AST classes
* implemented type-checking rules
* implemented lowering rules
* tests added
* commands run
* pytest result
* demo result
* `docs/status.md` update
* `docs/roadmap.md` update
* limitations

