# XGAP 当前开发进度与开发原则

更新至 2026-09-11。本报告区分当前工程实测与已记录的历史实验，不把测试条数当研究结果。

本次收尾核对的已验收代码为 **4825a2f8b432ab77c7aef41051273b90adffc8d0**，
提交时间为北京时间 **2026-09-11 11:24:35**，本地 HEAD 与跟踪的远程分支一致。
下文“已实现”以该提交及各里程碑的验收记录为界。随后开始的原生 OR/NOT
条件实现仍是未提交、未验收的工作区草稿，不计入已完成能力；整个 T1 尚未收尾。
本次为进度汇总，没有重新执行实验或重新估计历史统计。

此前方向代码里程碑：`8b6f06c0b0ba28e6de86fb617cf32d8f429a9465`。
9 月 10 日能力准入已验收并提交 d9c2858，按约暂停过夜后于次日上午恢复。
9 月 11 日 Optional/有限重复已验收；后续有限嵌套作用域通过原生分项，
最终完整回归也已通过，本步骤已验收。见 [重复路径报告](toy_backbone_t1_repetition.md) 与
[嵌套作用域报告](toy_backbone_t1_scoped_paths.md)。本文汇总 toy backbone、规划、绑定、
方向、能力准入、有限重复及嵌套作用域步骤；各步骤的原始结果与
失败记录仍保留在对应报告和 artifact 中。

## 可以汇报的进展

**无需 LLM 的确定性 backbone 已有真实执行闭环；整个 agentic system 尚未完成。**
开发重心已从 GrailQA 移回极小 toy graph。实际修复了 RDF 平行边身份丢失，
补齐有界路径原生执行与 selector，接通语义 DAG、受控语义绑定、候选生成、
观测、代价选择与真实执行，并闭合 IN 逻辑参考和有界 UNDIRECTED 执行。
Optional/有限 Bounded 也已从语法占位变为可执行语义，支持重复次数、零路径
和最短路径规则的独立对照。

| 当前证据 | 结果 | 说明什么 |
|---|---|---|
| 自建最小数据 | 5 节点、8 边、18 道完整 gold-chain 问题 | 可以人工检查，并在秒级局部测试中定位问题 |
| 确定性路径执行 | 18 题分别在真实 Neo4j/Fuseki 执行，36/36 完整答案正确；本轮经语义 DAG 入口再次成立 | 受测方向、身份、过滤、连接、Union、有界递归和 selector 可以实际工作 |
| 通用语义 DAG 组合 | 新增 8/8 用例正确，其中 6 个实际调用两个引擎；另有 8/8 独立 Cypher 目标通过 | Match/Traverse/Filter/Project/Join/Union/Aggregate/OrderLimit/Align 能组合成执行计划 |
| 候选规划与执行 | 8/8 程序、28/28 placement 候选答案正确 | 能在显式声明的完整等价源副本间生成、观察、选择并执行候选；尚非任意源发现或最优性证明 |
| 语义绑定与 agent 控制 | 5/5 受控查询、18/18 候选答案、10/10 独立原生对照正确 | 实体与结构化约束会进入实际查询；歧义及不支持的约束阻止派发 |
| 方向语义闭合 | 原 18/18 逻辑与参考答案正确；新增 9 题双后端 18/18 执行、18/18 独立目标正确 | IN 和有界 UNDIRECTED 保留边身份，正确区分自环、平行边及重复使用同一边 |
| 声明能力准入 | 8/8 查询、16/16 保留候选答案正确，12 个位置按预期被拒绝 | 原生语言/数据模型及 coordinator 要求对应实际拥有的执行节点，不再一律拒绝非空要求 |
| Optional/有限重复 | 新增 13 题双后端 26/26 执行、26/26 独立目标正确 | 重复次数与边数分开；最短选择尊重重复范围、nullable 子路径及零次分支 |
| 有限嵌套作用域 | 15 题双后端 30/30 程序和 30/30 独立目标正确；当前规划 gate 3/3 程序、6/6 候选正确 | 子路径内的 TRAIL/SIMPLE/SHORTEST 与外层拼接/过滤分开；本地比较中断和补测边界见专项报告 |
| 始终保留的联邦 slice | Neo4j 路径＋Fuseki 属性过滤＋coordinator join 得到 Alice→Cara | 组合开发没有破坏已贯通的真实最小链路 |
| 当前回归 | 日常 gate 358 passed，24.12 秒；完整回归 3,203 passed / 38 skipped，24 个 harness/example 入口通过 | 是软件验证；跳过项未被视为通过，测试数不能解释为真实数据准确率 |

例如，两条不同 a→b 边在计数时都被保留；没有匹配实体时 count 返回 0；同一
Match 被两个分支复用时只发出一次远程调用；交换两个后端的职责后答案不变。
再如 Bob 经无向路径最多两步回到自身：WALK 有 6 条完整路径，TRAIL 只剩
2 条使用不同平行边的路径，ACYCLIC 为 0；两后端均与独立预期相同。换绑定实体
或年龄门槛也会正确改变答案。这些是具体系统能力的证据。各组用例有重叠，
不能把表中通过次数相加当作独立 benchmark 样本量。详见
[语义组合](toy_backbone_t1_semantic_dag.md)、
[规划闭环](toy_backbone_t1_candidate_planning.md)、
[绑定闭环](toy_backbone_t1_semantic_binding.md) 和
[方向闭合](toy_backbone_t1_orientation.md) 报告。

## 还缺什么，为什么不等 GPU

当前阶段是 **受控语义能够驱动真实数据库的联邦查询原型**。已经走过“只有模块
和接口”的阶段；仍不能称为“其他都完成，只差接上 LLM”。

| 系统目标 | 当前实现程度 | 距离完整目标的缺口 |
|---|---|---|
| 语义、参考求值与编译 | 分层 IR、九类语义 DAG 操作的受测组合、有界路径及方向语义已实际运行 | 剩余 AST/typed 语义覆盖，所有支持组合的跨层一致性 |
| 联邦运行时 | 真实 Neo4j/Fuseki 插件，远程片段、数据交换、coordinator join/过滤/聚合/排序、共享祖先复用及错误传播 | 自动处理更一般的数据划分；超出有界内存行集的流式/批处理及 live 取消 |
| 确定性 planner | 等价源副本候选生成、能力准入、唯一片段观测、代价选择及执行连接 | 更一般的查询分解/源发现，代价校准与规模下好计划保留的证据 |
| Agent 与信息获取 | 预算受限 GoalLoop、类型化工具、实体澄清、绑定与约束落实、可选 ontology/model、已有 memory 机制 | 一般问题下有效的信息获取策略与真实理解质量；跨分布 memory 收益未成立 |
| Catalog / ontology / 数据 | 解析、映射、离线构建和 artifact 查询组件可用；tiny 链不依赖大 catalog 构建 | offline build→freeze/version→runtime-only lookup 的完整生命周期与跨入口验收，统一最小 failure replay |
| 远程执行与模型 | Slurm/远程工具与真实数据库执行已有历史证据；模型 provider、预算及失败记录已实现 | 最新 GPU 部署未产出模型答案，真实 NL→答案质量尚无新 backbone 的验收 |
| 轻量 UI | 已有本地澄清页面、控制器、HTTP 服务及选定会话提交接口 | 目前围绕既有实验 session；尚未形成连接新通用 backbone 的完整查询/计划/结果界面 |
| 研究评价 | 有 FinBench 部分正式物理实验、真实数据切片一致性与大量 toy correctness 证据 | 两主数据集完整 EQ1–EQ5、强基线、消融、鲁棒性与规模评价 |

因此不报一个没有验收分母的“完成百分比”。按现有里程碑，T0 已完成，T1 已有
多个真实验收步骤但尚未整体闭合；T2 和 T3 尚未验收。离完整系统主要还有三道门：

1. **确定性核心完整性**：补齐设计规定的剩余语义与执行组合；不能靠未支持时
   拒绝来宣称支持。每项都有模块测试和同一 tiny vertical slice 的正确答案。
2. **可复用系统闭环**：两条测试链独立验收，catalog 冻结后 runtime 只读，
   最小失败可离线重现，模型和 UI 接入同一个实际查询入口。无模型时确定性链仍可用。
3. **真实评价能力与研究证据**：先冻结 GrailQA-mini 做真实集成，再运行完整
   大数据 baseline/消融；正确性、成本、语义质量和鲁棒性分别报告。功能完成
   不自动意味着研究假设成立，更不能预先承诺 SIGMOD 级正面结果。

1. **规划与能力范围**：候选生成、代价选择和 agent 控制已连接；声明的原生/
   coordinator 要求已对应实际编译节点，任意领域能力名仍不自动得到支持。
   现有 placement 候选要求
   显式声明完整等价源副本；任意源发现、Traverse 内部自动跨库切分尚未实现。
   无可复用观测时仍 profile 所有唯一片段，代价模型是 proxy，未证明性能最优。
2. **语义覆盖**：IN、Optional 与有限 Bounded 的逻辑/参考缺口已闭合；
   有限嵌套非 WALK 已有显式 coordinator 执行，部分无界递归、原生复合布尔条件
   以及广泛 typed aggregate/order 仍需按设计逐项验收。
   已支持的有限 profile 不能代表任意程序支持，显式拒绝也不等于功能完成。
3. **Interpretation**：有 provider 接口与受控响应到真实答案的证据，尚无这套新
   backbone 上的真实模型 NL 准确率。固定 provider 可以先验收接口、约束落实与
   错误处理；模型质量等可用服务单独测量，不阻塞确定性工程。
4. **catalog 与 replay**：已有离线构建和只读查询组件，但所有入口的彻底解耦、
   freeze 生命周期及统一最小失败回放仍须作为 T2 验收，不能仅凭约定称完成。
5. **真实评价和 UI**：GrailQA-mini 集成、完整双数据集对照/消融和整体轻量 UI
   尚未闭合。当前无可信依据承诺全部设计指标达标日期。

## 已有研究结果的边界

历史 FinBench-derived 正式物理实验记录：在 32 个已见家族 held-out query 上，
计入当前查询选择成本的 XGAP/双计划实时 profiling 时间比为 **0.3096**，95% CI
[0.2509, 0.3683]；物理赢家选择为 **30/32**。这支持该范围内减少当前查询
profiling 成本，但 fixed-A、family-global 的选择相同，尚不能证明实例 memory
额外优势。冷家族 fallback **0/16** 的负结果必须同时报告。本轮引用已准入记录，
没有重算历史原始计时；1,888 次重复执行不是 1,888 个独立查询。

真实 Freebase 单 shard 的三道受支持查询，在联邦、完整 Fuseki 和独立源求值间
分别得到一致的 **103 / 6 / 202** 个答案。这是有限真实数据切片正确性，不是
GrailQA 全量准确率。完整历史依据、EQ1–EQ5 与基线适用范围见
[系统与实验评估](xgap_system_experiment_assessment_20260910.md)。

GrailQA 18 题的已知信息漏斗为 **18→10 catalog→6 retrieval→5 prompt**，
不是 5 题已经答对。3796988 虽构建成功，但覆盖零增益；另有旧模型候选未落实
实体约束，以及替代 GPU 的 ECC 启动失败。三者不能混为一个 catalog bug。
该 catalog 构建扫描 964 个 shard 两次，不是 3-hop 遍历；3-hop 也不推出有向图
直径为 6。保留这些失败，日常开发不再为其反复扫描、排队或 full run。

## 新 Goal 执行方式

已按用户指令持久化到 [docs/goal.md](../goal.md)、AGENTS 必读规则和现有持续
执行任务。第一阶段可以跳过 LLM，使用独立编写的完整预期链；顶层组合需要时
加入 semantic DAG，不能将所有语义强塞进一个 PathPatternQuery。

**模块隔离测试＋永远维护完整 vertical slice；Interpretation 与 deterministic
planning 两条测试链分开。** 日常 targeted tests＋toy E2E，只有共享核心或
milestone 边界做 broad regression。GrailQA catalog 只允许显式离线 build，成功
后 freeze/version；runtime 只读预建 artifact。失败保存最小输入与 observations
做本地 replay。GrailQA-mini 负责之后的真实集成，Full GrailQA 和其他大数据集
只负责最终评价、baseline 与消融。

9 月 10 日 capability milestone 完成后已暂停过夜；9 月 11 日 10:15 核实恢复，
现有定时任务已恢复每小时继续工程，之前的暂停要求已履行。
下一步按 T1 剩余语义覆盖→T2 interpretation/catalog/replay→T3 真实小
集成和最终评价推进。总体 Goal 保持 active。应用工具没有编辑活动 Goal 正文
的接口，权威 Goal 文件和持续执行规则承接这些新指令，未伪造完成或重建目标。
