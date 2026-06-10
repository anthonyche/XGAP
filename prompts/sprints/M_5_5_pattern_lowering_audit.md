# Sprint: M5.5 Pattern-Lowering Audit

## Goal

Audit the full M5 GPC-Lite pattern layer and deterministic lowering pipeline.

M5 introduced:

```text
GPC-Lite PathPatternQuery
  -> type_check_path_pattern()
  -> lower_path_pattern()
  -> LogicalPlan
  -> validate_plan()
  -> reference evaluation
```

M5.5 must verify that this pipeline is correct, deterministic, well-documented, and consistent with:

1. `docs/architecture.md`
2. `docs/roadmap.md`
3. `docs/status.md`
4. `docs/operator_semantics.md`
5. `docs/decisions.md`
6. `docs/semantic_audit.md`
7. M0-M5 implemented behavior

M5.5 must not add new functionality.

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
   * `src/xgap/pattern/types.py`
   * `src/xgap/pattern/typecheck.py`
   * `src/xgap/pattern/lowering.py`
   * `src/xgap/pattern/__init__.py`
   * `src/xgap/algebra/ops.py`
   * `src/xgap/algebra/conditions.py`
   * `src/xgap/algebra/validation.py`
   * `src/xgap/algebra/evaluator.py`
   * `src/xgap/algebra/pretty.py`
   * all existing tests
   * all existing examples

Then report:

* current milestone
* files you expect to modify
* files you will not modify
* audit plan
* expected documentation updates
* acceptance criteria

Do not modify code before reporting the audit plan.

## Allowed Changes

You may modify:

* `tests/test_pattern_lowering_audit.py`
* existing M5 tests only if the change strengthens assertions
* `examples/pattern_lowering_audit_demo.py`
* `docs/pattern_lowering_audit.md`
* `docs/architecture.md`
* `docs/roadmap.md`
* `docs/status.md`
* `docs/decisions.md`
* `scripts/run_acceptance.sh`

You may modify implementation files only if the audit reveals a real M5 semantic or correctness bug:

* `src/xgap/pattern/ast.py`
* `src/xgap/pattern/types.py`
* `src/xgap/pattern/typecheck.py`
* `src/xgap/pattern/lowering.py`
* `src/xgap/pattern/__init__.py`

If implementation files are modified, clearly explain:

* what semantic bug was found
* why it was a bug
* how it was fixed
* which test now covers it

## Forbidden Changes

Do not implement natural-language planning.

Do not implement LLM logic.

Do not implement disambiguation logic.

Do not implement backend capability profiles.

Do not implement GQL, Cypher, or SPARQL compilers.

Do not implement backend/database execution.

Do not implement optimizer rewrite rules.

Do not implement learned cost estimation.

Do not implement KGQA evaluation.

Do not implement full GPC.

Do not implement `Assignment`.

Do not implement `BindingRelation`.

Do not implement query-level joins or conjunctive graph query semantics.

Do not implement `Maybe` semantics.

Do not implement `Group` variable semantics.

Do not implement aggregation over repeated variables.

Do not implement bag semantics.

Do not implement null semantics.

Do not introduce new logical operators.

Do not change M0-M4.5 logical operator semantics.

Do not weaken existing tests.

Do not change semantics just to make tests pass.

## Audit Requirements

### 1. GPC-Lite Scope Audit

Verify and document that M5 implements only a path-centric GPC-Lite layer, not full GPC.

The implemented scope should include:

* `Var`
* `PatternVarType`
* `NodePattern`
* `EdgePattern`
* `Direction`
* `Rel`
* `Seq`
* `Alt`
* `Plus`
* `Star`
* `OptionalExpr` as unsupported or placeholder
* `Bounded` as unsupported or placeholder
* `Selector`
* `PathPatternQuery`
* `infer_schema`
* `type_check_path_pattern`
* `lower_regex`
* `apply_selector`
* `lower_path_pattern`

The implemented scope must exclude:

* full GPC
* assignment semantics
* conjunctive graph query joins
* `BindingRelation`
* `Maybe` runtime semantics
* `Group` variable runtime semantics
* backend query compilation
* NL parsing

### 2. AST Validity Audit

Add tests that verify the AST rejects or reports invalid structures:

* empty variable names
* whitespace-only variable names
* empty labels
* empty property names
* invalid selector `k`
* meaningless selector `k`
* unsupported `OptionalExpr` lowering
* unsupported `Bounded` lowering

Verify that AST objects are immutable where intended.

### 3. Type-Checking Audit

Add tests for the lightweight GPC-Lite type checker.

Verify:

* `source.var` infers `NODE`
* `target.var` infers `NODE`
* `edge.var` infers `EDGE`
* `path_var` infers `PATH`
* same variable reused with same type is accepted
* same variable reused with conflicting types is rejected
* repeated edge variables are rejected in M5
* `Alt` with asymmetric variable schemas is rejected
* `Alt` with matching variable schemas is accepted
* `Seq` with compatible shared variables is accepted
* `Seq` with incompatible shared variables is rejected
* `PathMode.WALK` with recursive expression and missing `max_depth` is rejected
* `PathMode.WALK` with positive `max_depth` is accepted

### 4. Direction Handling Audit

M5 may define:

* `Direction.OUT`
* `Direction.IN`
* `Direction.UNDIRECTED`

Verify:

* `Direction.OUT` lowers correctly.
* `Direction.IN` is accepted by the AST/type checker if designed that way, but lowering raises a clear `LoweringError`.
* `Direction.UNDIRECTED` is accepted by the AST/type checker if designed that way, but lowering raises a clear `LoweringError`.

M5 must not fake reverse or undirected traversal by changing existing logical operators.

### 5. Regex Lowering Audit

Verify that each regex AST node lowers to the expected canonical logical-plan shape:

```text
Rel(label)
  -> Selection(label(edge(1)) = label)
       Edges
```

```text
Rel(label=None, properties={})
  -> Edges
```

```text
Seq(a, b)
  -> Join(lower(a), lower(b))
```

```text
Alt(a, b)
  -> Union(lower(a), lower(b))
```

```text
Plus(a)
  -> Recursive(restrictor, lower(a))
```

```text
Star(a)
  -> Union(Nodes, Recursive(restrictor, lower(a)))
```

Verify:

* `Rel` with label and properties conjoins all edge conditions.
* `Plus` and `Star` with `WALK` require positive `max_depth`.
* lowering emits only existing logical operators.
* lowering does not call the evaluator.
* lowering does not call any LLM.
* lowering does not emit backend query strings.

### 6. Descriptor Lowering Audit

Verify source and target descriptors lower correctly.

Source descriptor:

```text
NodePattern(label="Person", properties={"name": "Alice"})
```

must lower to conditions over:

```text
label(first)
first.name
```

Target descriptor:

```text
NodePattern(label="Company", properties={"risk": "High"})
```

must lower to conditions over:

```text
label(last)
last.risk
```

Verify that descriptor constraints are applied before selector wrapping.

### 7. Selector Mapping Audit

Verify that each selector maps to the audited M4 selector shape.

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

Verify selector mapping is deterministic.

### 8. Full Lowering Pipeline Audit

Add tests for complete pattern lowering:

```text
PathPatternQuery
  -> type_check_path_pattern()
  -> lower_path_pattern()
  -> validate_plan()
  -> evaluate_pathset()
```

Use at least these queries:

#### ANY SHORTEST TRAIL

```text
ANY SHORTEST TRAIL p = (x)-[:Knows]+->(y)
```

Expected plan:

```text
Projection [*, *, 1]
  OrderBy [PATH]
    GroupBy [SOURCE_TARGET]
      Recursive [TRAIL]
        Selection [label(edge(1)) = "Knows"]
          Edges
```

#### ALL SHORTEST ACYCLIC

```text
ALL SHORTEST ACYCLIC p = (x)-[:Knows]+->(y)
```

Expected plan:

```text
Projection [*, 1, *]
  OrderBy [GROUP]
    GroupBy [SOURCE_TARGET_LENGTH]
      Recursive [ACYCLIC]
        Selection [label(edge(1)) = "Knows"]
          Edges
```

#### STAR query

```text
ALL TRAIL p = (x)-[:Knows]*->(y)
```

Expected core shape includes:

```text
Union
  Nodes
  Recursive [TRAIL]
    Selection [label(edge(1)) = "Knows"]
      Edges
```

### 9. Determinism Audit

Verify that lowering is deterministic.

For the same `PathPatternQuery` object, repeated calls to `lower_path_pattern(query)` must produce equal logical-plan structure or identical `format_plan(plan)` output.

Verify this for:

* `Rel`
* `Seq`
* `Alt`
* `Plus`
* `Star`
* full `ANY SHORTEST TRAIL` query
* full query with source/target descriptors

### 10. Reference Evaluation Audit

Verify that lowered plans evaluate correctly on a small graph.

Use the paper-style Knows graph:

```text
n1 -e1:Knows-> n2
n2 -e2:Knows-> n3
n3 -e3:Knows-> n2
n2 -e4:Knows-> n4
```

Also include a graph with multiple edge labels:

```text
n1 -likes-> n2
n2 -has_creator-> n3
n1 -knows-> n4
```

Audit:

* `Rel("Knows")` returns only Knows edges.
* `Seq(Rel("Likes"), Rel("Has_creator"))` returns compatible two-step paths.
* `Alt(Rel("Knows"), Rel("Likes"))` returns both labels.
* `Star(Rel("Knows"))` includes zero-length paths.
* source descriptor filters by `first`.
* target descriptor filters by `last`.

### 11. Documentation Audit

Codex must create or update:

* `docs/pattern_lowering_audit.md`
* `docs/status.md`
* `docs/roadmap.md`
* `docs/architecture.md`
* `docs/decisions.md`

#### `docs/pattern_lowering_audit.md`

Must include:

* audited files
* audited AST classes
* audited type-checking rules
* audited lowering rules
* selector mapping table
* unsupported M5 features
* known implementation choices
* commands run
* result summary

#### `docs/status.md`

Must update:

```text
M5.5 Pattern-Lowering Audit: DONE
Next milestone: M6 Backend Capability Profiles
```

Only mark M5.5 DONE after acceptance passes.

#### `docs/roadmap.md`

Must include or update M5.5:

```text
M5.5 Pattern-Lowering Audit
```

Mark it DONE only after acceptance passes.

M6 and later must remain TODO.

#### `docs/architecture.md`

Must clearly state:

* M5 implements GPC-Lite, not full GPC.
* GPC-Lite is the structured path-pattern layer.
* Logical algebra remains the audited path-algebra layer.
* LLM planning remains future work.

#### `docs/decisions.md`

Must include or update design decisions for:

* GPC-Lite scope
* deterministic lowering
* type checking before lowering
* unsupported full-GPC features
* no assignment/binding semantics in M5

### 12. Acceptance Script

If `examples/pattern_lowering_audit_demo.py` exists, `scripts/run_acceptance.sh` must run it.

## Tests

Add:

* `tests/test_pattern_lowering_audit.py`

The audit tests should cover:

1. AST invalid inputs.
2. variable type inference.
3. conflicting variable types.
4. repeated edge variable rejection.
5. asymmetric `Alt` variable schema rejection.
6. unsupported direction lowering.
7. unsupported `OptionalExpr` and `Bounded` lowering.
8. regex lowering shapes.
9. descriptor lowering shapes.
10. selector mapping shapes.
11. full query lowering shapes.
12. deterministic repeated lowering.
13. lowered plan validation.
14. lowered plan reference evaluation.
15. future features remain unimplemented.

Run:

```bash
./scripts/run_acceptance.sh
```

## Acceptance Criteria

* `./scripts/run_acceptance.sh` passes.
* pytest passes.
* all existing demos pass.
* `examples/pattern_lowering_audit_demo.py` passes if added.
* `docs/pattern_lowering_audit.md` exists.
* `docs/status.md` marks M5.5 DONE only after tests pass.
* `docs/roadmap.md` marks M5.5 DONE only after tests pass.
* M6 and later remain TODO.
* No parser, compiler, backend, optimizer, LLM, disambiguation, cost-estimator, KGQA, full GPC, assignment, or BindingRelation logic is added.

## Final Report

Report:

* changed files
* audit tests added
* audited AST classes
* audited type-checking rules
* audited lowering rules
* semantic bugs found, if any
* semantic bugs fixed, if any
* commands run
* pytest result
* demo result
* documentation updates
* remaining limitations
