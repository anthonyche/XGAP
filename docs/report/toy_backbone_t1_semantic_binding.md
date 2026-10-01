# T1：语义绑定、可执行约束与 agent 控制闭环

2026-09-10。原来的 resolver 已能返回候选 ID，但缺少把通用候选真正写入新
语义 DAG 执行条件的连接。本轮补上这个连接，并复用现有 GoalLoop、只读
artifact catalog、代价规划器和后端插件；不新增按题硬编码的 native 模板。

真实 Neo4j/Fuseki 验证：**5/5 查询、18/18 候选计划答案、10/10 独立目标查询**
正确，原两后端 T18 vertical slice 仍通过。完整共享核心验收 **3,098 passed /
38 skipped in 665.34s**，24 个 harness/example 入口全部通过。此连接步骤已
验收；完整 T1/T2/T3 和系统 Goal 仍未完成。

## 实现及可观察行为

`bind_semantic_query` 将候选 ID 通过显式类型化注册表写入 `$hole` 槽位。
ENTITY 必须有唯一权威选择，放在实际节点身份 descriptor 或正向合取的身份
等式内；装饰性输出名称、未使用的 required hole、未注册或类型不匹配的
候选均不能通过。SOURCE 单独绑定逻辑数据源；PREDICATE/TYPE 绑定 schema
标识，CONSTRAINT 绑定有限 JSON scalar。物理代价不能替用户选择不同含义。

`SemanticConstraint` 新增可选结构化 `predicate`。旧文本格式/哈希保持兼容；
只有携带受支持 predicate 的命名约束才能编译。Match/Traverse 使用既有
typed condition AST，Filter 使用既有 row condition DSL；它们与已有条件
取 AND，不能覆盖原条件。Hard 与 relaxable 约束都保留且执行，没有自动放宽。
不透明的文本要求及尚不支持的约束位置仍明确报错，不宣称已经实现。

`run_agentic_semantic_query` 使用现有有界 GoalLoop：解析工具 → 绑定/准入 →
候选规划 → 唯一观测 → 代价选择 → 执行。工具类型、allowlist、预算、结果
observations 与失败记录保留。唯一源观测失败后不派发 serving，不自动重试。
无效绑定和编译失败发生在数据库调用之前。该入口接受预构造的语义模板；
NL 到模板的模型质量仍属于独立 Interpretation 测试链。

## 人工可核对的结果

原 5 节点/8 边、18 道 path gold 和 8 个组合 gold 全部不变。新增的
`datasets/backbone_binding_v1` 包含五题 NL、带槽位程序、gold path 子查询、
预期 logical plan、独立 Cypher/SPARQL、预期 typed rows，以及离线编写的
catalog 和 candidate value 注册表。B04 是纯节点查询，无 path 子查询。

| 用例 | 条件 | 真实答案 | 候选正确数 |
|---|---|---|---:|
| B01 | Alice knows 的人员，age >= 30 | Cara，通过 e4 | 4/4 |
| B02 | 改为 Bob，age >= 30 | Cara，通过 e2 | 4/4 |
| B03 | Alice，age >= 45 | 空集 | 4/4 |
| B04 | Match Alice 且 age >= 30 | a，age 30 | 2/2 |
| B05 | Alex 有歧义，受控澄清选择 Bob | Cara，通过 e2 | 4/4 |

五次 query goal 合计 **18 次观测 + 9 次 serving = 27 次后端调用**。
其他候选的验证额外 25 次；独立目标 10 次；旧 slice 2 次，均与 serving
成本分开。B05 是已收集选择的测试 fixture，不声称本轮真实向用户提问。
模型调用及输入/输出 token 均为 0。冷暖混合小图计时不能作性能对比。

## 验证与失败回放

- 新模块最终 **29 passed in 1.06s**：五题完整链、独立 RDF 对照、歧义与
  无效绑定阻止派发、约束合取、catalog/后端失败各只尝试一次。
- 日常 toy gate 首次 **154 passed in 11.18s**，旧 demo 正常，明确保留 M5
  IN lowerer 缺口；之后新增七项覆盖由上述 29 项及 broad suite 验证。
- 语义/解析/artifact/bridge 兼容边界 **57 passed in 24.02s**。
- Broad acceptance：原 session11079 已 exit0，**3,098 passed / 38 skipped
  in 665.34s**，24 个 harness/example 入口全部通过。日志
  `/tmp/xgap-t1-binding-acceptance.log`。所有本轮进程均已终止，不重复轮询或
  重跑已通过检查。真实验收后生产源码和冻结 fixture 哈希仍一致。

第一次真实运行 session37831 exit1：B01 四个候选答案已正确，独立 SPARQL
对照的测试适配器却未声明 `rdf_terms_v1`，读取类型化结果时失败。停止后两
服务均正常关闭，未自动重试。代码修正并新增五题离线 RDF 对照回放后，才
在新目录做修正版本验收：session90516 exit0，两服务正常关闭，无强杀。
生产查询本身没有该编码错误，旧运行记录保留，不能隐去失败分母。

原始失败：`/Users/anthonyche/xgap-data/t1-binding-native-20260910/result.json`。
修正版本：`/Users/anthonyche/xgap-data/t1-binding-native-20260910-corrected/result.json`。
可随仓库复核的 [验收记录](../../experiments/artifacts/toy_backbone_t1_binding_20260910.json)
保留版本哈希、绑定证据、选中计划、候选答案及失败摘要。
日志分别为 `/tmp/xgap-t1-binding-native.log`、`native-corrected.log`（同一前缀）。
本地测试日志前缀 `/tmp/xgap-t1-binding-`，后缀为 `focused-initial.log`、
`focused-final.log`、`boundaries.log` 和 `replay.log`。

## 结论与下一步

这一步证明受控候选解析、实际语义绑定、约束编译、有限候选规划与真实执行
可以贯通，且答案对实体和条件的变化有正确响应。它没有证明任意 NL 理解、
完整 ontology 推理、自动源发现或最优信息获取。当前物理规划只在显式声明
的完整等价副本之间选位置；仍可能 profile 全部唯一片段，成本全部计入。

继续用同一小图闭合 M5 IN logical/reference 及剩余 path/typed semantics。
T2 对所有入口验收 offline build/freeze 与 runtime-only catalog 边界、最小
failure replay 和 Interpretation；T3 先冻结真实小集成，再做大数据评价。
GPU 与 GrailQA catalog 构建均不应阻塞这条开发链。
