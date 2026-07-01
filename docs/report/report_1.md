# XGAP 当前进展汇报

## 1. 项目目标与当前定位

XGAP 是一个 **ambiguity-aware natural-language-to-graph-query planner**。它的长期目标是将自然语言问题转化为可执行、可解释、可验证的图查询计划，并进一步编译到 GQL、Cypher、SPARQL 等目标查询语言。

当前阶段的核心目标不是直接让 LLM 生成 Cypher、SPARQL 或 GQL 字符串，而是先建立一个 **可验证、可执行、可审计的 deterministic planning core**。这样做的原因是：自然语言理解可以有歧义，LLM 输出也可能不稳定；但一旦候选结构化查询进入 XGAP 的核心层，后续的类型检查、逻辑计划生成、验证和参考执行必须是确定性的。

当前已经完成并审计的 deterministic core 是：

```text
GPC-Lite PathPatternQuery
  -> type_check_path_pattern()
  -> lower_path_pattern()
  -> LogicalPlan
  -> validate_plan()
  -> reference evaluation
```

当前 scope 是 **path-centric graph query / regular path query fragment**，并新增了一个 bounded focused quantified-pattern fragment。也就是说，XGAP 当前支持路径中心的图查询、正则路径查询，以及 M6 范围内的聚焦树形量化模式；它仍不是 full GPC，也不是 arbitrary conjunctive graph pattern matching。任意复杂的图模式匹配、Assignment、query-level join、bag/null semantics 等仍属于未来扩展。

## 2. Overall Roadmap

| Milestone | Goal | Status | Main output | Why it matters |
| --- | --- | --- | --- | --- |
| M0 Project harness / skeleton | 建立包结构、文档、示例、测试入口 | DONE | `src/xgap/**`、`docs/**`、`examples/**`、`tests/**`、`pyproject.toml` | 提供可持续迭代的工程骨架 |
| M1 Path / PathSet / PropertyGraph data model | 实现路径数据模型和有向 labeled property graph | DONE | `Path`、`PathSet`、`SolutionSpace`、`PropertyGraph` | 为后续路径代数执行提供基础数据对象 |
| M2 Core path algebra | 实现 `Nodes(G)`、`Edges(G)`、`Selection`、`Union`、`Join` | DONE | core algebra evaluator 与条件 AST | 支持固定长度路径构造、过滤、集合并、路径连接 |
| M2.5 Plan validation / pretty print / metadata | 增加逻辑计划验证、格式化、算子元数据 | DONE | `validate_plan()`、`format_plan()`、operator metadata | 让逻辑计划可检查、可展示、可调试 |
| M3 Recursive algebra | 实现递归路径代数 | DONE | `Recursive` with `WALK`、`TRAIL`、`ACYCLIC`、`SIMPLE`、`SHORTEST` | 支持正则路径查询中的 Kleene-plus 和 restrictor |
| M4 SolutionSpace algebra | 实现 `GroupBy`、`OrderBy`、`Projection` | DONE | `PathSet -> SolutionSpace -> PathSet` | 支持 selector-style path semantics，如 ANY SHORTEST |
| M4.5 Logical operator semantic audit | 审计 M0-M4 逻辑算子语义 | DONE | `docs/semantic_audit.md`、semantic audit tests/demo | 确认逻辑代数层与文档语义一致 |
| M5 GPC-Lite Pattern AST + Lowering | 定义结构化路径模式 AST，并确定性 lowering 到 LogicalPlan | DONE | `PathPatternQuery`、type checker、lowering rules | 将结构化 query intent 接入 path algebra |
| M5.5 Pattern-lowering audit | 审计 M5 pattern layer 与 lowering pipeline | DONE | `docs/pattern_lowering_audit.md`、audit tests/demo | 确认 GPC-Lite 到 LogicalPlan 的转换正确、确定、边界清晰 |
| M6 Bounded Focused Quantified Pattern Semantics | 增加 bounded、focus-oriented、rooted-tree quantified pattern 语义 | DONE | `FocusedQuantifiedPatternQuery`、minimal `BindingRelation`、focused binding operators、quantified lowering / evaluation | 支持 count、ratio、universal、NONE 等聚焦量化条件 |
| M6.5 Quantified-pattern semantic audit | 审计 M6 quantified-pattern semantics 与 lowering pipeline | TODO | semantic audit doc、audit tests/demo | 确认 counting、ratio、negation、bounds、determinism、execution boundary |
| M7 Backend Capability Profiles | 表示不同后端能力边界 | TODO | backend profile schema / compatibility checker | 为后续编译器选择和 unsupported feature 报告打基础 |
| M8 GQL / Cypher / SPARQL compilers | 将 LogicalPlan 编译到目标查询语言 | TODO | GQL、Cypher、SPARQL compiler | 把逻辑计划连接到真实图数据库/端点 |
| M9 Optimizer and cost feature extraction / cost estimator | 引入逻辑优化与成本特征 | TODO | optimizer rules、cost feature interface | 为计划改写和候选计划排序提供基础 |
| M10 LLM planner and grounding | 引入自然语言 planner 与 grounding | TODO | LLM-facing schemas、planner placeholder 扩展 | 让自然语言问题生成候选结构化查询 |
| M11 Disambiguation and top-K ranking | 对候选解释进行排序和保留 top-K | TODO | disambiguation / ranking modules | 面向 ambiguity-aware planning 的核心能力 |
| M12 KGQA evaluation | 增加 KGQA 数据集与评估流程 | TODO | dataset loader、evaluation harness | 评估系统端到端效果 |
| Future: fuller GPC-inspired conjunctive graph pattern extension | 扩展到更完整的 GPC-style graph pattern semantics | FUTURE | Assignment / query-level join 语义 | 支持更复杂的图模式匹配，但需超出当前 M6 focused tree fragment |

## 3. 当前已经完成的系统主线

当前系统可以按七层理解：

```text
Layer 1: Path data model
Layer 2: Path-algebra logical operators
Layer 3: Logical-plan validation / pretty printing / reference evaluator
Layer 4: GPC-Lite structured pattern representation
Layer 5: Deterministic lowering
Layer 6: Bounded focused quantified-pattern layer
Layer 7: Audits and tests
```

### Layer 1: Path data model

实现了 `Path`、`PathSet`、`SolutionSpace` 和 `PropertyGraph`。

- `Path` 是 node、edge、node 交替序列。
- zero-length path 只包含一个 node。
- one-length path 形如 `source, edge, target`。
- `PathSet` 是去重路径集合。
- `PropertyGraph` 是有向 labeled property graph，并可把 nodes / edges 转换为 `PathSet`。

### Layer 2: Path-algebra logical operators

实现了路径代数逻辑算子：

```text
Nodes(G), Edges(G), Selection, Union, Join,
Recursive, GroupBy, OrderBy, Projection
```

这些算子使用 `PathSet` 和 `SolutionSpace`，没有引入 `NodeScan`、`EdgeExpand`、`Filter`、`Aggregate`、`Project` 等额外逻辑算子名称。

### Layer 3: Logical-plan validation / pretty printing / reference evaluator

实现了：

- `validate_plan()`：检查算子输入/输出类型流是否正确。
- `format_plan()`：稳定格式化逻辑计划。
- reference evaluator：在内存图上执行 LogicalPlan，作为语义参考实现。

### Layer 4: GPC-Lite structured pattern representation

M5 定义了结构化 `PathPatternQuery`，用于表示路径中心的模式查询 intent。它不是自然语言 parser，也不是 full GPC parser。

### Layer 5: Deterministic lowering

`lower_path_pattern()` 先调用 `type_check_path_pattern()`，再把 GPC-Lite AST 确定性转换为逻辑计划，并在最后调用 `validate_plan()`。

### Layer 6: Audits and tests

已完成两轮关键审计：

- M4.5：logical operator semantic audit。
- M5.5：pattern-lowering audit。

最近一次 M6 验证范围包括：

- `python -m pytest`: 234 passed。
- `python examples/quantified_pattern_demo.py`: passed。
- `./scripts/run_acceptance.sh`: passed，包含 harness check、pytest、既有 examples 和 M6 quantified-pattern demo。

## 4. Path Algebra Logical Operator 设计

XGAP 的 logical operators 对齐 path algebra paper，而不是临时发明一套 graph query operator vocabulary。当前逻辑代数只使用 `PathSet` 和 `SolutionSpace` 两类核心数据对象。

| Operator | Input | Output | 实现语义 | 当前状态 |
| --- | --- | --- | --- | --- |
| `Nodes(G)` | Graph | `PathSet` | 每个 graph node 转成一个 zero-length path | Implemented |
| `Edges(G)` | Graph | `PathSet` | 每个 graph edge 转成一个 one-length path | Implemented |
| `Selection` | `PathSet` | `PathSet` | evaluate child 后用 Condition AST 过滤 path | Implemented |
| `Union` | `PathSet x PathSet` | `PathSet` | evaluate 两个 child，返回去重集合并 | Implemented |
| `Join` | `PathSet x PathSet` | `PathSet` | 只连接 `left.last() == right.first()` 的 path，并去掉重复中间节点 | Implemented |
| `Recursive` | `PathSet` | `PathSet` | Kleene-plus recursive path construction，按 mode 约束路径 | Implemented |
| `GroupBy` | `PathSet` | `SolutionSpace` | 将 path 组织为 partitions / groups，并初始化 rank | Implemented |
| `OrderBy` | `SolutionSpace` | `SolutionSpace` | 只更新 rank，不改变 membership mapping | Implemented |
| `Projection` | `SolutionSpace` | `PathSet` | 按 rank 和稳定 tie-breaker 选择 partitions / groups / paths | Implemented |

### Nodes(G)

`Nodes(G)` 调用 graph 的 node-to-path conversion，把每个节点转换为一个 zero-length path：

```text
n -> Path(n)
```

输出是 `PathSet`。

### Edges(G)

`Edges(G)` 把每条边转换为 one-length path：

```text
source -edge-> target
```

输出也是 `PathSet`。

### Selection

`Selection` 先 evaluate child，得到 `PathSet`，再使用 Condition AST 过滤路径。当前 Condition 支持：

- node label / edge label equality。
- node property / edge property equality。
- `first`、`last`、indexed node / edge reference。
- path length equality。
- boolean `AND`、`OR`、`NOT`。

### Union

`Union` 分别 evaluate left 和 right child，然后返回 deduplicated `PathSet` union。`PathSet` 本身通过 path equality 去重。

### Join

`Join` 分别 evaluate left 和 right child，只连接满足：

```text
left.last() == right.first()
```

的路径。连接时共享节点只保留一次：

```text
(n1, e1, n2) Join (n2, e2, n3)
=> (n1, e1, n2, e2, n3)
```

### Recursive

`Recursive` 表示 Kleene-plus，而不是 Kleene-star。深度 1 包含 child path；深度 k 通过继续 join child path 扩展。`max_depth` 统计的是 child path 拼接次数，不一定等于最终图路径边数。

支持的 modes：

- `WALK`: 允许重复节点和重复边；必须提供正的 `max_depth`。
- `TRAIL`: 不允许重复边；允许重复节点。
- `ACYCLIC`: 不允许重复节点。
- `SIMPLE`: 只允许首尾闭合时出现 `first == last` 的一次重复。
- `SHORTEST`: 按 source-target pair 保留最短 path；同长度 ties 会保留。

Kleene-star 当前通过：

```text
Union(Nodes(G), Recursive(...))
```

表示，而不是把 `Recursive` 本身改成 star。

### GroupBy

`GroupBy` 的类型流是：

```text
PathSet -> SolutionSpace
```

它不删除 path，也不排序，只组织 path 到 partition/group，并把 path、group、partition rank 初始化为 1。

支持的 grouping keys：

- `NONE`
- `SOURCE`
- `TARGET`
- `LENGTH`
- `SOURCE_TARGET`
- `SOURCE_LENGTH`
- `TARGET_LENGTH`
- `SOURCE_TARGET_LENGTH`

### OrderBy

`OrderBy` 的类型流是：

```text
SolutionSpace -> SolutionSpace
```

它保留：

- paths
- partitions
- groups
- path-to-group assignment
- group-to-partition assignment

只更新 rank function。

支持的 order keys：

- `PARTITION`
- `GROUP`
- `PATH`
- `PARTITION_GROUP`
- `PARTITION_PATH`
- `GROUP_PATH`
- `PARTITION_GROUP_PATH`

### Projection

`Projection` 的类型流是：

```text
SolutionSpace -> PathSet
```

它按 rank 和 deterministic tie-breakers 排序，然后应用三个限制：

```text
num_partitions, num_groups, num_paths
```

其中 `None` 表示 `*`。例如：

```text
Projection [*, *, 1]
```

表示每个 retained group 最多保留一个 path。

## 5. Path Pattern Query 到 LogicalPlan 的 deterministic lowering

M5 定义了 GPC-Lite structured pattern representation。当前实现的主要对象包括：

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
- `OptionalExpr` / `Bounded` as unsupported placeholders
- `Selector`
- `PathPatternQuery`

`PathPatternQuery` 不是字符串 parser 的输出格式，也不是 backend query language。它是 XGAP 内部的结构化 query-intent object。

### Canonical lowering rules

| Pattern construct | Lowering result |
| --- | --- |
| `Rel(label)` | `Selection(label(edge(1))=label)` over `Edges` |
| `Seq(a,b)` | `Join(lower(a), lower(b))` |
| `Alt(a,b)` | `Union(lower(a), lower(b))` |
| `Plus(a)` | `Recursive(restrictor, lower(a))` |
| `Star(a)` | `Union(Nodes, Recursive(restrictor, lower(a)))` |
| Source descriptor | `Selection` over first node |
| Target descriptor | `Selection` over last node |
| Selector | `GroupBy / OrderBy / Projection` wrapper |

### Selector mapping

| Selector | Logical-plan shape |
| --- | --- |
| `ALL` | `Projection(*,*,*) -> GroupBy(NONE)` |
| `ANY` | `Projection(*,*,1) -> GroupBy(SOURCE_TARGET)` |
| `ANY k` | `Projection(*,*,k) -> GroupBy(SOURCE_TARGET)` |
| `ANY SHORTEST` | `Projection(*,*,1) -> OrderBy(PATH) -> GroupBy(SOURCE_TARGET)` |
| `ALL SHORTEST` | `Projection(*,1,*) -> OrderBy(GROUP) -> GroupBy(SOURCE_TARGET_LENGTH)` |
| `SHORTEST k` | `Projection(*,*,k) -> OrderBy(PATH) -> GroupBy(SOURCE_TARGET)` |
| `SHORTEST k GROUP` | `Projection(*,k,*) -> OrderBy(GROUP) -> GroupBy(SOURCE_TARGET_LENGTH)` |

### Example: ANY SHORTEST TRAIL

Pattern-level query：

```text
ANY SHORTEST TRAIL p = (x)-[:Knows]+->(y)
```

在当前 `format_plan()` 输出中 lowers to：

```text
Projection [*, *, 1]
  OrderBy [PATH]
    GroupBy [SOURCE_TARGET]
      Recursive [mode=TRAIL]
        Selection [label(edge(1)) = "Knows"]
          Edges
```

这说明：

- `[:Knows]` 被降低为 edge label selection over `Edges`。
- `+` 被降低为 `Recursive`。
- `TRAIL` 成为 recursive restrictor。
- `ANY SHORTEST` 被降低为 `GroupBy(SOURCE_TARGET)`、`OrderBy(PATH)`、`Projection(*,*,1)`。

## 6. GPC 对 XGAP 的启发与吸收

GPC 对 XGAP 的作用是提供结构化 graph/path pattern 的设计启发，但当前 XGAP 没有实现 full GPC。

需要明确区分：

- GPC 不是当前的 logical operator layer。
- GPC 不是 backend language。
- XGAP 当前没有实现 full GPC semantics。
- XGAP 当前吸收的是 GPC-inspired 的 path-centric structured pattern representation 和 lightweight type checking。

### 6.1 Pattern components

GPC 启发 XGAP 表示以下 pattern components：

- descriptors: variable + label / properties
- node pattern
- edge pattern
- direction
- condition
- repetition
- concatenation
- union
- restrictor
- query-level structure

当前 XGAP 只采用 path-centric subset：路径模式、正则路径表达式、selector、restrictor、endpoint descriptor。它不支持 arbitrary conjunctive graph pattern matching。

### 6.2 Variable and type checking

XGAP GPC-Lite 当前实现的 type-checking 规则包括：

- `source.var` 和 `target.var` 推断为 `NODE`。
- `edge.var` 推断为 `EDGE`。
- `path_var` 推断为 `PATH`。
- 同名变量不能具有冲突类型。
- repeated edge variables 在 M5 中被拒绝。
- asymmetric `Alt` variable schemas 被拒绝。
- selector `k` 必须 meaningful 且为正数。
- `WALK` recursive patterns 需要正的 `max_depth`。
- `Direction.IN` 和 `Direction.UNDIRECTED` 可以被 AST / type checker 表示，但 M5 lowering 不支持，会明确报错。

### 6.3 What is not absorbed yet

以下 GPC 相关能力尚未实现：

- full GPC
- assignment semantics
- general GPC assignment relations
- query-level join
- conjunctive graph query
- `Maybe` semantics
- `Group` variable semantics
- bag/null semantics
- aggregation over repeated variables

原因是当前目标是先构建 path-centric deterministic core，并在 M6 增加 bounded focused quantified-pattern fragment。Full GPC 需要 general assignment relations、query-level unification 等语义，这会超出当前 `PathSet` / `SolutionSpace` 与 M6 minimal `BindingRelation` 的表达范围。

## 7. 设计指标与 correctness strategy

### 7.1 Operator-level correctness

M4.5 semantic audit 检查了逻辑算子语义，包括：

- `Nodes(G)`
- `Edges(G)`
- `Selection`
- `Union`
- `Join`
- `Recursive`
- `GroupBy`
- `OrderBy`
- `Projection`

它验证了类型流：

```text
PathSet -> PathSet
PathSet -> SolutionSpace
SolutionSpace -> PathSet
```

同时覆盖 core algebra、recursive modes、SolutionSpace、selector-style semantics、empty input 和 deterministic tie-breaking。

### 7.2 Pattern-lowering correctness

M5.5 pattern-lowering audit 检查：

- AST validity。
- type checking。
- regex lowering shape。
- source / target descriptor lowering。
- selector mapping。
- repeated lowering determinism。
- lowered plan validation。
- reference evaluation。
- future features remain unimplemented。

### 7.3 Determinism

当前 deterministic strategy 是：

- 同一个 `PathPatternQuery` 总是 lowering 到同一个 canonical logical-plan structure / `format_plan()` 输出。
- lowering 不调用 LLM。
- lowering 不依赖 backend。
- lowering 不调用 reference evaluator 来决定计划结构。
- lowering 后立即 `validate_plan()`。

这使 XGAP 可以把 LLM 或其他 planner 的不确定性限制在候选 query intent 生成阶段，而不是让不确定性进入核心 algebra execution。

### 7.4 Reference evaluator

reference evaluator 是当前语义基准：

- 它在内存 `PropertyGraph` 上执行 LogicalPlan。
- 它用于测试 operator semantics 和 lowering correctness。
- 它不是生产级 backend execution engine。
- 未来 GQL / Cypher / SPARQL compiler 可以用它作为语义对照。

## 8. 当前 Boundary：能 claim 什么，不能 claim 什么

### We can claim

- XGAP has an audited path-algebra logical operator layer。
- XGAP supports a path-centric graph query fragment。
- XGAP supports GPC-Lite structured `PathPatternQuery`。
- XGAP supports bounded focused `FocusedQuantifiedPatternQuery` with M6 set-valued binding semantics。
- XGAP deterministically lowers `PathPatternQuery` to `LogicalPlan`。
- XGAP deterministically lowers focused quantified patterns to validated logical plans。
- XGAP validates and reference-evaluates logical plans。
- XGAP supports selector/restrictor-style path plans in the reference evaluator。
- XGAP has harness, docs, tests, examples, and audit reports。

### We cannot claim yet

- We do not support full natural-language-to-query。
- We do not support full GPC。
- We do not support general conjunctive graph pattern queries。
- We do not support general Assignment or arbitrary query-level joins。
- We do not compile to GQL / Cypher / SPARQL yet。
- We do not execute on Neo4j / SPARQL / GQL backend yet。
- We do not have backend capability profiles yet。
- We do not have optimizer rewrite rules yet。
- We do not have learned cost estimator yet。
- We do not have disambiguation / top-K ranking yet。
- We do not have KGQA evaluation yet。

## 9. 下一步计划

推荐的下一步顺序：

```text
M6.5 Quantified-pattern semantic audit
M7 Backend Capability Profiles
M8 GQL / Cypher / SPARQL Compilers
M9 Optimizer + cost feature extraction
M10 LLM planner and grounding
M11 Disambiguation + top-K ranking
M12 KGQA evaluation
```

### M6.5 Quantified-pattern semantic audit

M6.5 的目标是审计 M6 quantified-pattern semantics 与 lowering pipeline。预期工作包括：

- 审计 `FocusedQuantifiedPatternQuery` AST validity。
- 审计 canonical quantifier、bound checking、deterministic lowering。
- 审计 `BindingRelation` 与 focused binding operators。
- 审计 count、ratio、ALL、NONE、focus-only query。
- 审计 reference evaluation 与 unsupported-feature boundary。

M6.5 不应引入新语义，也不应实现 backend/compiler/optimizer/LLM 功能。

### M7 Backend Capability Profiles

M7 的目标是把 backend capability 从 compiler logic 中分离出来。预期工作包括：

- 定义 backend profile 数据结构。
- 定义 reference evaluator profile。
- 定义 Neo4j / Cypher profile。
- 定义 SPARQL endpoint profile。
- 定义 GQL profile。
- 实现 compatibility checker：

```text
LogicalPlan + BackendProfile -> supported / unsupported / reason
```

M7 不应直接实现 compiler，也不应直接执行 backend query。它的重点是回答：

> 当前 LogicalPlan 能不能被某个后端支持？如果不能，原因是什么？

### M8 Compilers

M8 在 M7 capability boundary 明确后，再实现 GQL、Cypher、SPARQL compiler。compiler 应保留 logical semantics，并对 unsupported feature 给出明确错误。

### M9 Optimizer + cost feature extraction

M9 才引入逻辑 rewrite rules 和成本特征提取。当前 optimizer 仍是未来工作，不应提前 claim。

### M10-M12

M10 开始接入 LLM planner 和 grounding。M11 处理 disambiguation / top-K ranking。M12 增加 KGQA evaluation，用于衡量端到端效果。

## 10. PPT-ready slide outline

### Slide 1: Problem and XGAP goal

- 自然语言图查询存在歧义。
- 直接生成 Cypher/SPARQL/GQL 难以验证。
- XGAP 目标：ambiguity-aware NL-to-graph-query planner。
- 当前重点：deterministic planning core。

### Slide 2: Why not direct NL -> Cypher?

- LLM 输出可能不稳定。
- backend query string 难以统一验证。
- 缺少中间逻辑层会降低可审计性。
- XGAP 先生成结构化 intent，再 lowering 到 LogicalPlan。

### Slide 3: Overall roadmap

- M0-M6 已完成。
- 当前已具备数据模型、路径代数、递归、SolutionSpace、GPC-Lite lowering、bounded focused quantified-pattern semantics、审计。
- M6.5-M12 仍是规划阶段。
- 下一步：Quantified-pattern semantic audit。

### Slide 4: Path algebra logical layer

- Logical operators 对齐 path algebra。
- Primary object: `PathSet`。
- Secondary object: `SolutionSpace`。
- 不引入 ad hoc graph operator vocabulary。

### Slide 5: Operator semantics

- `Nodes` / `Edges`: graph 到 path。
- `Selection` / `Union` / `Join`: core path algebra。
- `Recursive`: WALK / TRAIL / ACYCLIC / SIMPLE / SHORTEST。
- `GroupBy` / `OrderBy` / `Projection`: selector semantics。

### Slide 6: SolutionSpace and selector semantics

- `GroupBy`: organize paths into partitions/groups。
- `OrderBy`: update ranks only。
- `Projection`: select by ranks and limits。
- 支持 ANY、ANY SHORTEST、ALL SHORTEST 等 selector-style plans。

### Slide 7: GPC-Lite PatternQuery layer

- `PathPatternQuery` 位于 logical algebra 之上。
- 表示 node/edge descriptors、regex path expressions、selector、restrictor。
- 当前是 path-centric subset，不是 full GPC。
- Type checking 在 lowering 前执行。

### Slide 8: Deterministic lowering example

- 示例：`ANY SHORTEST TRAIL p = (x)-[:Knows]+->(y)`。
- `Rel` -> `Selection over Edges`。
- `Plus` -> `Recursive`。
- selector -> `GroupBy / OrderBy / Projection`。
- lowering 后立即 `validate_plan()`。

### Slide 9: Correctness and audit strategy

- M4.5 审计 logical operators。
- M5.5 审计 pattern lowering。
- M6 实现 bounded focused quantified-pattern semantics。
- pytest 和 acceptance script 已通过。
- reference evaluator 作为语义基准。

### Slide 10: Current boundary

- 可以 claim：path-centric fragment、deterministic lowering、validated/evaluated LogicalPlan。
- 不能 claim：full NL-to-query、full GPC、conjunctive graph patterns、backend compiler/execution。
- 当前边界清晰，避免 fake future features。

### Slide 11: Next steps

- M6.5 Quantified-pattern semantic audit。
- M7 Backend Capability Profiles。
- M8 Target compilers。
- M9 Optimizer / cost features。
- M10 LLM planner and grounding。
- M11-M12 disambiguation and KGQA evaluation。

## 11. Suggested speaking notes

这部分可以作为汇报时的口播参考。

1. 我们当前做的不是直接把自然语言交给 LLM 生成 Cypher 或 SPARQL，而是在中间建立一个确定性的规划核心。这样每一步都可以检查、测试和审计。

2. XGAP 的逻辑层对齐 path algebra。当前所有已实现的逻辑算子都围绕 `PathSet` 和 `SolutionSpace` 展开，没有引入临时的 graph operator 名称。

3. `Recursive` 支持多种 path restrictor，包括 `WALK`、`TRAIL`、`ACYCLIC`、`SIMPLE` 和 `SHORTEST`。这使系统可以表达 regular path query 中的核心递归路径语义。

4. `GroupBy`、`OrderBy` 和 `Projection` 提供 selector-style semantics。比如 ANY SHORTEST 可以被表达为先按 source-target 分组，再按 path length 排序，最后每组取一个 path。

5. GPC 对系统的启发主要体现在 pattern layer，而不是 logical operator layer。我们当前实现的是 GPC-Lite，也就是路径中心的结构化 pattern representation。

6. M5 的关键成果是把 `PathPatternQuery` 确定性 lowering 到 LogicalPlan。这个过程先 type check，再构造 logical operators，最后 validate plan。

7. M5.5 的重点是审计这个 lowering pipeline。审计覆盖 AST validity、type checking、lowering shape、selector mapping、determinism 和 reference evaluation。

8. M6 的新增能力是 bounded focused quantified-pattern semantics。它支持 focus node、rooted tree、count / ratio / ALL / NONE 等量化条件，但仍不是 full QGP 或 full GPC。

9. 当前边界也很重要：我们还没有 full natural-language-to-query、没有 full GPC、没有后端 compiler、没有 Neo4j/SPARQL backend execution。这些都在后续里程碑中。

10. 下一步最合理的是 M6.5 quantified-pattern semantic audit。先审计 M6 的 counting、ratio、negation、bounds、determinism 和 execution boundary，再进入 backend capability profiles。

11. 总结来说，当前 XGAP 已完成的是一个可执行、可验证、可审计的 path-centric deterministic core，并新增了 bounded focused quantified-pattern fragment；它为后续 LLM planner、backend compiler 和 KGQA evaluation 打下基础。

## Checklist

[ ] Can be converted to PPT
[ ] Roadmap is clear
[ ] Completed vs planned boundary is clear
[ ] Claims are conservative
[ ] Next steps are clear
