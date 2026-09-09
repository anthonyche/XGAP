# XGAP 设计复盘与持续工程计划（2026-09-09）

## Material Passport

- 技能：academic-research-suite / experiment-agent；工程设计与运行验证。
- 主仓库：`/Users/anthonyche/Developer/XGAP`，起点 `a91aed6`。
- 项目镜像 `.../.chatgpt-projects/.../XGAP` 仍在 `eacbe50`，不能作为最新状态。
- 本轮读取边界：三份来源 PDF 均完成结构完整性检查和全文提取；主线架构、代数语义、近期设计决策、修复报告与实验覆盖表已经重点审阅。81 份既有工程 Markdown 文档（约 17.6 万空白分隔词）已建立目录，历史长文尚未逐段复核完毕。**全文提取或目录覆盖不等于全文审阅。** 后续从阅读清单继续，不声称“全部文档已读完”。
- 证据范围：当前代码、独立 RDFLib 执行、既有文档中的远程验收记录、浏览器可见的 CWRU 状态。本轮尚未重新审计 FinBench 原始远程结果。
- 这份报告不更改原始论文、冻结协议、评价分母或已接纳结果。

## 1. 设计判断

XGAP 已有可执行的联邦系统核心，当前问题是不同入口尚未汇合成同一条可验证的答案链。FinBench 从已定义查询家族进入物理执行；GrailQA 从开放自然语言进入语义候选生成。前者的成功不能推导后者的语义可靠性。

三层历史表述需要保留来源，但论文主线必须使用当前架构：

| 设计来源 | 主要对象和目标 | 当前需明确的边界 |
|---|---|---|
| Workshop 论文 | 解释、逻辑计划、跨平台计划；可信度/歧义/多样性/成本 | 是研究提案；其中旧逻辑算子名不是当前代数 API |
| OntoXGAP 白皮书 | 在 ontology-relative deviation ≤ ε 下最小化执行成本 | 语义接近不等于理解正确；其安全剪枝和复杂度结论仍需正式证明 |
| M15 主线 | 部分绑定的语义 DAG；选择信息获取和执行动作，最小化完整成本 | ontology、LLM、catalog 是可选工具；后端是黑盒；已有实现主要是有限策略/家族 |

推荐保持现有 M15 方向，不再回到以 PathPatternQuery 表示整个系统。PathPatternQuery 是 Traverse 的子表示；语义 DAG、agent 控制、联邦执行计划和路径代数分层保留。下一步以“同一用户问题产生可解释、可执行、可核对的答案”为验收单位。

```mermaid
flowchart LR
  Q[自然语言与硬约束] --> C[只读 catalog / ontology / 会话]
  C --> I[有界语义候选]
  I --> V[类型、可见性、绑定与语义校验]
  V --> P[能力检查与联邦计划]
  P --> N[Neo4j 片段]
  P --> F[Fuseki 片段]
  N --> J[显式身份对齐与协调器连接]
  F --> J
  J --> A[明确答案投影与规范化]
  A --> E[独立解释及答案评价]
```

## 2. 当前 bottleneck 与优化策略

| 优先级 | 已有证据 | 瓶颈 | 行动和成功信号 |
|---|---|---|---|
| P0 | 主仓库与项目镜像不同；status/roadmap 是多年里程碑追加记录 | 工作入口和“当前状态”不集中 | 固定主仓库，建立本轮状态文件及读取清单；每轮先核对 commit、dirty 状态、活动作业 |
| P0 | 旧 18-query 有 8 个 catalog 缺失、4 个检索缺失、1 个 prompt 缺失；5 个参考解释可达 | 可用信息不足 | 保留所有 18 题分母；先读取 3796988 的新旧覆盖增减，分别定位实体、关系、类型、prompt；不把 eligibility 修复预先当作八个缺失的原因 |
| P0 | 上传响应按最新校验离线重放，两个问题共四个候选合法；这不是新模型准确率 | 模型重复填写 AST 与 binding/component 引用，接口负担过高 | 保留已实现的共用一次修复预算；下一独立版本仅让模型输出语义选择，由程序生成可唯一推导的机械引用。不能唯一确定时显式失败/澄清 |
| P0 | 四个候选在 D195 可编译，但未验证真实答案 | RDF/属性图身份、类型谓词、答案列仍需显式契约 | 本轮 D196 接通独立引擎 → HTTP → typed RDF → 答案投影；下一步真实 Fuseki/Neo4j 与数据快照验证 |
| P1 | M15 已有双后端、连接、计量和有限重规划 | 家族模板与开放解释尚未统一；任意 DAG 尚不能编译 | 为目标查询结构逐项列出 representation / validation / compilation / execution / answer-equivalence 覆盖；先固定方向多跳，再交集/聚合/比较，禁止近似替代不支持语义 |
| P1 | 已有 FinBench 22 块、1,888 次执行的接纳记录；固定策略、family-global 与 memory 同选 | 尚无实例级 memory 的独立收益 | 保留现有结果；按冻结的 EQ1–EQ5 覆盖表补 FinBench 语义和 GrailQA 物理。未来 workload 或模型改变要有独立协议，不能按已有结果调到“显著” |
| P2 | 有有限预算、调用账本、native 服务生命周期与 UI | streaming、取消、规模资源控制和通用交互不完整 | 在正确答案闭环之后加入有界分批交换、背压与取消；UI 展示现有 trace/result，不另造查询语义 |

新的 RDF 契约还暴露了三个具体陷阱：URI 与同字面字符串不能连接；不同数据类型/语言的 literal 不能抹平；不同结果文档中相同 blank-node 标签不能直接作为全局 ID。SPARQL JSON 明确携带这些类别，blank node 仅在一个结果对象内有身份意义。[W3C SPARQL JSON](https://www.w3.org/TR/sparql11-results-json/)

运行说明也存在历史值漂移：`cwru_vllm_experiment_backend.md` 原表格仍写 8,192 serving context，而当前 JSON 配置及 runbook 为 12,288（8,192 输入 + 4,096 输出）。本轮已按当前配置修正文档并保留更正说明，没有改模型、预算或服务器配置。后续运行应读取机器配置及实际请求计数，不能只依赖旧说明中的数值。

本轮采用显式 opt-in，保留旧实验的字符串模式；新 typed 模式遇到未携带作用域的 blank node 明确拒绝。答案比较是 RDF term set equality，尚不是 GrailQA 官方数值/日期/答案值等价评价。

Query-local catalog 的现有两遍构建仅保留名称、别名和类型，没有事实边或 k-hop 子图。因此“catalog 已建好”仍不足以执行 GrailQA：H4 还必须从推理侧可用来源构建事实数据快照，并测量该快照的覆盖范围与加载成本。不能从 gold 逻辑式反向抽取需要的边，再把它视为真实数据闭环。

## 3. 理论与研究证据的边界

1. 语义合法、ontology 可接受、编译可用、执行成功、答案正确是五个独立指标。不能把任意一项代替后一项。
2. 白皮书的 dominance 需要比较可继续完成的计划空间，不能只比较当前两个标量。例如前缀成本 0 但剩余成本 100 的状态，不支配前缀成本 1、剩余成本 1 的状态。正式剪枝结论需要同一语义等价类、兼容剩余能力、可延续性和可证明的成本界。
3. GP 置信区间或近邻误差界不是天然的确定性 admissible bound。预算内搜索可报告 oracle regret 和错剪率，不能仅因变量名包含 lower/upper 就声称全局最优。
4. Ontology-based Entity Matching 论文的 OGK 是特定键/匹配语义；它的复杂度和匹配保证不能移植为 XGAP 的语义保证。需要明确哪些映射是输入假设、哪些工具证据可验证、哪些由用户确认。
5. 18-query 是开发数据，150-query 含历史开发重叠；已见家族、未见实例和冷家族必须分开。保持查询为统计单位，不以重复执行次数增加有效样本量。
6. GrailQA 历史 `c_sem` 审计还发现：query anchor 与 candidate realization 由同一响应提出，存在自对齐得零分的退化风险。接口合法化并不能消除这个研究问题。M15 已区分未确认解释与有明确基准的 relaxation；应先审计现有 GrailQA 锚点来源和分数分布，再决定独立版本的锚点协议，不能通过放宽/重调旧分数制造 ε 效果。

## 4. Milestones 和停止条件

| 阶段 | 产物 | 验收及下一步 |
|---|---|---|
| H0 文档与状态校准 | 主仓库、阅读清单、证据索引、活动作业快照 | 当前仍有历史长文待逐段审阅；发现与主线冲突时明确标记，不默默覆盖 |
| H1 远程闭环 | 单个作业的提交记录、状态、日志、结果、失败分类 | 优先复用 OnDemand 已登录会话；3796988 运行期间保持服务器 checkout；凭据/网络失效才请求用户介入 |
| H2 答案契约 | D196 typed RDF / 显式映射 / 答案投影 / 独立引擎测试 | 本轮实现；完整本地回归后增加独立 live gate，不能标为 GrailQA 完整答案闭环 |
| H3 候选接口简化 | 版本化语义 sketch → 确定性组装 → 原校验 | 旧响应对比 + 同样18题的独立开发实验；固定模型、catalog和预算；记录仍失败的每层 |
| H4 目标数据执行 | 推理侧数据快照、catalog/ontology/identity 契约、可执行查询集合 | 不能用 gold 查询构建部署数据；保留数据覆盖分母，真实两后端计划的答案与独立 oracle 一致 |
| H5 统一实验 | 两数据集 EQ1–EQ5 的 baseline / ablation / metric / split 矩阵 | 每个保留格子有实际结果；新总体、科学假设或研究方向变化由用户决策 |
| H6 规模与轻量 UI | 分批执行、资源测量、作业及结果查看 | 不干扰 CLI/harness；失败和取消状态可观测 |

每轮执行：读取本轮状态 → 选择一个阻塞闭环的可验证问题 → 写目标/假设/范围 → 实现 → 针对性差异测试 → 完整必要回归 → 运行小规模实验（环境可用时） → 记录实际结果与下一步。无代码变化或新失败时不重复全套回归；不把一次外部失败静默重试为成功。

## 5. 本轮工程证据

- 继承并完成了工作区已有的 RDF draft，未丢弃先前改动。
- 153 个相关测试通过、1 个真实 Fuseki gate 跳过，包括独立 RDFLib + 本机 HTTP 的完整编译/执行/答案路径。
- 自定义类型谓词、资源身份等于/不等于、URI/literal/type/language 区分、明确答案列、错误与空答案、合法 Unicode 均有直接行为验证。
- 全套回归：**2,503 passed / 37 skipped，604.92 秒**；harness 检查和 19 个既有 examples 全部通过。持久验收记录见 `experiments/artifacts/d196_rdf_answer_contract_local_20260909.json`，本轮状态见 `docs/engineering_state.md`。
- 远程终端可见 3796988 为 RUNNING；仅观察现有任务，本轮未提交新 CPU/GPU/backend 作业。
- 后续 Chrome 浏览器接口显示文件页已跳转 CWRU 登录，终端控制超时；已请求用户恢复登录。未获取新的作业日志，不把旧界面快照当作当前状态。

## 6. 来源与继续阅读

主线依据：`docs/agentic_architecture.md`、`docs/m15_agentic_federated_core.md`、`docs/architecture.md`、`docs/operator_semantics.md`、`docs/decisions.md`（尤其 D169、D172、D192–D195）、`docs/report/research_question_dataset_coverage_v1.md`、`docs/report/grailqa_candidate_feedback_v1.md`、`docs/report/directed_native_rows_v1.md`、`docs/report/grailqa_parallel_repair_handoff_20260909.md`。

三份只读来源为 Workshop 论文、OntoXGAP 白皮书和 Ma 等人的 *Ontology-based Entity Matching in Attributed Graphs*。它们的 PDF 提取及结构检查存于本机 `/tmp/xgap-review-20260909/`，原件保持不变。完整路径、内容哈希、章节索引和阅读状态记录在 `docs/report/xgap_document_inventory_20260909.json`；这是阅读清单，不是研究结果或引用真伪认证。
