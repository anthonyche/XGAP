# XGAP Active Goal — Toy-first Development

更新：2026-09-10，依据用户明确指令。本文是现有 active Goal 的权威开发补充，
覆盖旧 roadmap、status、报告和 automation 中冲突的开发优先级；保留所有历史
结果和已冻结的最终评价协议。当前第一要务是快速完成系统，修复实现与设计不匹配之处。

## 总目标

持续将 XGAP 建成可用于 SIGMOD 级实验的完整 agentic federated graph query
system，包含正确的语义、确定性规划/编译、真实 Neo4j/Fuseki 可插拔执行、可选
LLM interpretation、离线数据/catalog/ontology 准备、可复现实验及必要轻量 UI。
按明确 milestones 循环设计、实现、测试、实验与复盘。只有凭据、VPN/必要人工
服务器操作、外部 artifacts 或实质研究方向决策需要用户介入；此次 toy-first
方向调整已获明确授权，不重复确认。

## 开发原则

1. **Development dataset 可以是自己构建的极小 toy graph。** 用于快速测
   correctness、接口、planner、semantics、compiler、execution，以及快速 debug
   和迭代。开发进度以完整系统正确工作衡量，不以跑通 GrailQA 衡量。
2. 先准备一个极小图和十几个 query，初始目标约 16–18 个，覆盖核心 operator。
   每题必须有完整预期链：

   **NL → gold PathPatternQuery → expected logical plan → expected target query
   → expected result**。

   对不能由单个 PathPatternQuery 表示的顶层 Join/GroupBy 等操作，显式补上
   semantic DAG wrapper 和 path 子查询；不能把整个查询系统强行降格成 path IR。
   图、问题、类型化答案、计划和目标查询都应小到能人工检查。预期答案独立于待测
   实现编写，不能直接把当前实现输出存成“正确答案”。
3. 第一阶段可以 **skip LLM**，把 gold 语义 fixture 直接输入确定性链，证明
   XGAP backbone 工作正常。这是合法的 toy 模块/集成测试，不是自然语言准确率。
   大数据集推理仍保持 gold isolation；不将评价实体补入 inference catalog、
   排序器或部署事实。
4. 永久维护两条独立测试链：
   - **Interpretation**：NL 与允许上下文 → 候选/选定语义，与 gold meaning 和
     硬约束对照。固定 provider 响应用于接口测试，真实模型质量单独验收。
   - **Deterministic planning**：固定语义 → logical plan → target query / native
     fragments / federated plan → execution → expected typed result。不得依赖
     LLM、GrailQA 原始语料或 catalog build。
5. **模块隔离测试＋永远维护一条完整 vertical slice。** 每次相关修改后，最小
   toy E2E 必须仍能工作。局部测试全通过不代表系统完成；核心设计中尚未支持的
   算子/组合必须明确列为缺口并修复，不能用“显式拒绝”冒充已经支持。
6. **GrailQA 不是开发环境。** 不集中力量追逐高成本 benchmark 的各种小 bug。
   Toy backbone 跑通之后，才用小型冻结的 GrailQA-mini 检查真实集成。Full
   GrailQA 和其他大数据集只负责最终真实评价、规模实验、baseline 与消融比较。
7. **GrailQA catalog build 与 runtime 彻底解耦。** Build 是显式 offline
   preprocessing；成功后 freeze/version。Runtime 只能读取/查询准备好的 artifact，
   不能扫描语料、重建、自动下载或隐式生成 catalog。缺失/不兼容时清楚报出准备
   条件；后续有意 rebuild 必须产生新版本并保留旧版本。
8. 构建 **failure replay**：保存最小复现输入、相关版本、model/tool/backend
   observations 和失败边界，用本地确定性回放代替重复高成本运行。回放证据与真实
   外部运行分开；不得静默重试失败的外部动作。
9. 节约开发时间与 token：日常修改优先 targeted tests＋tiny vertical slice；在
   milestone 或共享核心边界运行 broad offline suite。无新代码或疑点不反复全量
   回归；模块测试不以 GrailQA 成功为门槛。不要为抽象完备再添加无当前必要性的
   guard、审计层或协议框架。

## 测试阶梯

| 层级 | 责任 | 不能替代什么 |
|---|---|---|
| Toy E2E | 保证整个系统能跑、受控语义能得到正确结果；LLM 可跳过 | 真实 benchmark 准确率/性能 |
| Module tests | 保证局部语义、接口、planner、compiler、execution 正确且可快速回放 | 完整组合链的正确性 |
| GrailQA-mini | 以冻结小样本和预建目录保证真实数据/服务集成 | 官方全榜或完整评价 |
| Full GrailQA 与其他大数据集 | 真实评价、规模、baseline、消融 | 日常开发/debug 环境 |

保留 FinBench、GrailQA 两个已选主数据集和原 EQ1–EQ5 最终评价义务，不围绕通过
的 toy cases 重写研究问题，也不将 toy、replay 或部分 shard 当真实 benchmark 结果。

## 下一组 milestones

- **T0：最小图与完整 query fixtures。** 明确身份、typed scalar、方向、多步路径、
  重复/循环和空结果，给出等价 Neo4j/Fuseki 编码及联邦 placement。覆盖 Nodes、
  Edges、Selection、Union、Join、Projection、GroupBy、OrderBy、Recursive 及
  对应 path modes/SHORTEST；具体组合冻结后逐一列出 expected chain。先交付不需
  模型或大语料的第一条完整确定性 slice。
- **T1：确定性 backbone 与设计缺口。** 用真实 planner/compiler/runtime 跑全部
  fixtures，对照独立参考与小型真实数据库。交付 operator-by-layer 覆盖表，修复
  具体缺口，每次修改保持 tiny slice。验收依据是正确行为，不是测试数。
- **T2：Interpretation、catalog 边界与 replay。** 同一 fixture 集验收 interpretation
  接口及语义；独立 offline build/freeze 与 runtime read-only lookup；证明 runtime
  不会调用 builder，并离线复现已有失败，不重跑外部动作。
- **T3：真实小集成，然后最终评价。** Toy backbone 正常后，接入 GrailQA-mini、
  真模型与真后端；最后才开展冻结的大数据集 baseline/消融。UI 复用同一接口。

功能验收可以排期，正面效果、memory 优势、ontology 收益或 SIGMOD 录用不能承诺。

## 当前进度与被替代的工作

- T0 已验收：5 节点、8 边、18 题完整 gold chain；参考 lowerer/求值器匹配 17/18
  （IN 缺口保留）；独立目标查询在真实 Neo4j/Fuseki 上 36/36 匹配；生产编译器与
  运行时的第一条联邦 slice 返回 Alice→Cara。Full regression 2,963 passed /
  38 skipped，24 个 harness/example 入口通过。完整 backbone 尚未完成。
- T1 正在进行：显式 RDF 边身份表示/生产编译支持已验证，8 题在真实 Neo4j/Fuseki
  上 16/16 完整路径匹配，原联邦 slice 继续通过；focused 185 passed / 1 skipped，
  兼容性 99 passed。旧普通 RDF 行为与 toy gold 未改变。下一步补齐 node-only/Union、
  递归/selector 等生产执行覆盖；IN 原生行已验证，M5 logical lowerer 缺口仍保留。
  本步没有重复全仓库回归，不宣称完整 T1/backbone 完成。
- D205：受控 provider＋真实 Neo4j/Fuseki 已验证受支持查询的答案；不是真实 LLM
  自然语言准确率。
- D207：GPU 启动健康检查软件已验收；最新真实 GPU 启动仍失败，无新模型答案。
- D208：CPU 配对测量入口已在 `7e09a56` 实现，focused **112 passed / 1 skipped**；
  后来的 T0 全回归也覆盖该软件，native 验收仍未执行。**新的三百万行 shard 测量没有启动**。按本次用户指令，
  原大 shard 开发实验在执行前延期；保留代码，合适时用于 toy 测试，再按相应
  milestone 验收，不为“收尾”单独消耗一轮 full regression 或真实大图实验。
- catalog 8＋4＋1 诊断和 GPU 分配不再排在日常开发首位；已知问题保留，后续按
  集成需要处理。立即下一步是 T1 的剩余核心算子闭环。

## Goal 工具状态

当前应用 Goal 工具支持创建、读取及完成/阻塞状态更新，不提供活动目标正文编辑。
现有总体 Goal 保持 **active**，未假装完成或重新创建。本文、AGENTS 必读规则、
engineering state 与现有 heartbeat 共同持久化新的执行依据；应用中旧 Goal 文本
不能覆盖这条后续明确用户指令。
