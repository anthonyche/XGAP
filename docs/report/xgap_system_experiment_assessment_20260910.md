## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: plan + interpretation of existing recorded results
- Origin Date: 2026-09-10 (北京时间)
- Verification Status: ANALYZED / source-inspected; not a fresh reproduction of the remote FinBench statistics or a completed new benchmark
- Version Label: xgap_system_experiment_assessment_20260910_v1
- Scope: 当前实现边界、GrailQA 失败归因、无 LLM 工程路线、EQ1–EQ5 指标与对照、条件化排期
- Sources: 主仓库架构、状态与实验报告；已阅读的三份项目 PDF；本文直接链接的论文与官方代码库。旧工程阅读清单仍有 7 篇选读材料，不能称所有历史文档均逐字读完。

## 结论与当前实现程度

**XGAP 已经是能在真实图数据库上执行受支持查询的研究原型，但不能称为“其余全部完成，只差 LLM”。** 已有模块的存在、受控验收、自然语言端到端有效性、论文贡献证据，是四个不同的完成标准。目前前三者之间仍有缺口，完整论文指标也没有闭合。

| 环节 | 已有证据 | 尚未完成或不能据此推出的结论 | 没有 LLM 时能否推进 |
|---|---|---|---|
| 语义表示与代数 | 分层 semantic / agent / tools / runtime / algebra；确定性验证与参考求值；固定 OUT/IN 路径及部分条件有原生编译 | 任意语义 DAG、所有算子组合与所有后端的完整覆盖；一般等价性/最优性保证 | 能，输入明确的结构化语义程序 |
| 数据与 catalog / ontology | Parquet 解析、名称/别名/类型候选、映射接口、带类型 literal 与身份规则 | 通用实体链接、高覆盖可复用索引、完整 GrailQA 事实覆盖、完整 FIBO/跨库 ontology 管线 | 能，主要是 CPU / 存储工作 |
| Neo4j + Fuseki | 真数据库、原生查询、资源边与属性分布、方向/实体/类型/标量约束、答案归一化 | 任意查询自动分解及多个完整物理计划的普遍覆盖 | 能 |
| agent 控制与物理规划 | 有限预算、类型化工具、错误/能力不可用观察、局部执行规划、家族记忆 | 一般“获取信息还是直接执行”的有效策略与跨分布收益；大规模共享子计划复用/流水线收益 | 能，大部分可用确定性工具/固定解释测量 |
| question → provider → native answer | 统一 API/CLI；受控 HTTP provider 与真实数据库的三例已返回正确答案 | 真实 Qwen 从自然语言到正确答案的成功率；歧义情况下的一般选择策略 | 可先测连接、编译与执行；模型质量需服务 |
| LLM 服务与远程运行 | 固定版本/预算、受控调用、Slurm 提交/日志/失败保留与资源切换 | 最新部署没有产出推理；正常长期服务仍需真实验证 | 接口可离线测试，真实效果不能替代 |
| 实验与 UI | FinBench 有已准入的正式物理实验；脚本/CLI 与大量回归 | 两个主数据集完整 EQ1–EQ5；可用的整体轻量 UI；完整论文实验 | CPU 实验与简单结果 UI 可推进 |

真实数据的一个已完成切片：第一份完整 Parquet shard 有 3,247,670 行，Fuseki 中 3,233,752 条去重事实，Neo4j 中 541,675 条资源边。一个类型/英文名称查询返回 103 对结果，联邦执行、完整 Fuseki 查询、独立 Arrow 源数据求值三者相同；另有 6 / 202 个答案的后续查询一致。这证明受支持切片的真实执行正确性，不能外推完整 Freebase、18 题或 GrailQA 准确率。见 [真实答案桥接](freebase_native_answer_bridge_v1.md) 与 [统一问题入口](freebase_question_execution_v1.md)。

## 测试方式：分层定位，同时保持小规模端到端贯通

不能只跑 unit tests，也不能每次都依赖一次昂贵的 full run 找错。采用以下验收顺序；每个已贯通切片保留一个端到端 smoke，防止“各自通过，接口组合却失败”。

1. **确定性组件测试**：数据解析、实体身份、literal 类型、语义验证、映射和编译。记录支持与拒绝行为；不能把未实现返回空答案当成正确。
2. **真实后端联动测试**：同一明确语义，在联邦、完整单库、独立参考求值之间比较完整答案；覆盖正例、空结果、重复值、反向边、类型、数值/字符串差异和预算耗尽。
3. **固定解释的 CPU 系统实验**：所有方法接收同一查询与数据，比较物理路线、信息获取、端到端时间、传输和规划开销。明确输入是结构化语义，不冒充 NL 理解成绩。
4. **真实模型小闭环**：自然语言 → grounding → 实际约束 → 计划 → 后端答案。每个问题必须终结为答案或明确失败，保留所有分母；先开发切片再扩大。
5. **冻结协议后的正式实验**：固定数据/查询/比较器/预算，交错顺序与重复测量，按 query 聚合，报告区间和分层结果。正式 full run 不承担日常调试职责。

现有仓库 AGENTS.md 要求每个软件 milestone 在 focused tests 之后完成 broad offline suite 与 examples；继续遵守。仅文档变化、无新代码或新疑点时不反复跑完整回归。**2,922 个测试通过是软件回归证据，不是 2,922 个真实实验，更不等于完整系统达到设计指标。**

## 为什么 GrailQA 18 题没有闭合

### 失败一：catalog / retrieval / prompt 的信息漏斗

真实 CPU 作业 3796988 已 COMPLETED / 0:0，历时 3:56:26。构建程序确实完成，覆盖没有改善：

| 阶段 | 参考解释所需实体/关系/有效类型共同可见的问题数 | 本阶段新增排除 |
|---|---:|---:|
| 全部开发问题 | 18 | — |
| catalog | 10/18 | 8 |
| retrieval Top-20 | 6/18 | 4 |
| prompt Top-4 | 5/18 | 1 |

其中 catalog 的实体覆盖是 10/18，关系与有效类型均 18/18；首先卡在实体。后面的 20/4 截断又丢失候选。这里的 5/18 是联合可达性诊断，不是答案准确率，也不表示这五题模型已经答对；可替代等价解释同样需要明确的评估规则。

旧/新构建的 15 个覆盖单元全部零增益、零损失；每题实体列表及顺序也相同。修过的“先判资格再截断”没有解决这组失败。不能因为文件 hash 改了就宣称 catalog 变好，更不能继续用同一修补重复扫描。见 [比较结果](grailqa_catalog_comparison_3796988.md)。

### 失败二：生成候选没有把实体声明落实为查询约束

历史真实模型作业 3796877 的 18 题留下 49 个候选。后来按明确类型/grounding 规则回放，只有 4 个候选（来自两题）存活；但它们仍缺少必须的实体等值约束。在 JSON 的 entity 列表里写出一个实体，不等于 WHERE/过滤条件中真正限定该实体。执行它们可能变成查询整个类别，所以在要求锚定实体的目标下 **0 个获准派发**。这既涉及输出接口与生成质量，也涉及约束落实，不能归因于 GPU 排队。

新的 inline AST/slot 输出接口、定向编译、真实答案入口已经实现；它们的真实模型效果尚未测得。不能把旧响应的离线重新解释当作新模型准确率。见 [候选到执行的边界](grounded_candidate_execution_v1.md)。

### 失败三：当前替代 GPU 作业在模型启动前遇到硬件错误

H100 3799513 一直待资源，已按授权在 PENDING 时取消。替代作业 3799649 在双 L40S 节点 gput069 启动，但遇到 `CUDA error: uncorrectable ECC error encountered`，最终 FAILED / 1:0，没有题目推理。GPU 1 初始已有三个不可纠正 ECC 事件。容量/型号正确不代表可执行 CUDA。

D207 已补上逐卡微型 CUDA 分配/写入/同步，以及 owned server 退出后立即停止 readiness 等待；51 项 focused、2,922 passed / 38 skipped 全回归、23/23 harness/examples 已通过。还没有提交修正部署，也没有新的真实 GPU 成功证据。坏节点须显式排除，H100 仍优先；不能宣称软件修好了硬件。

**3799513 和 3799649 原定都是冻结 18 题的语义接口实验，backend execution=false，paper admission=false。即使成功，也不会自动给出完整问答实验；仍需将真实生成结果接到已实现的 native-answer 入口。**

## catalog 究竟是什么，为什么耗时，与 hop 有什么关系

catalog 是推理时查“这个名字可能是哪一个 ID、有哪些关系和类型、如何映射”的目录/索引。实际事实图回答“这些 ID 之间究竟有什么边/属性”。这两者有不同的数据准备和完整性要求。当前 catalog 不包含可直接执行的事实边快照。

当前构建器大致做两次流式源扫描：第一次从名称/别名中选择候选，第二次补所选实体的名称、别名和类型。它从问题提取规范化的连续 1–8 token 短语，仅匹配英语 name/alias 和 MID 格式实体，再做词面排序与每题 Top-50 限制。这是一个受限的词面实体链接器，无法假定能处理所有缩写、别名缺失、非连续提及与同名歧义。实现见 [grailqa_local_catalog.py](../../src/xgap/experiments/grailqa_local_catalog.py)。

源数据有 964 个 shard。两轮扫描与解码会付出大规模输入成本，即使最终输出只有约 14.4 MB。新构建记录 13,773 秒（约 3 小时 49 分）；历史旧构建 2,703 秒（约 45 分）。**这两次不是控制环境的配对性能实验，尚不能断言慢了约五倍就是某段算法造成的；I/O、缓存、调度/CPU 和解码分别耗时还没被测清。** 已确认的是重复从源扫描和最终的小目录大小不是同一个成本量级。

这段代码没有做 3-hop 子图展开。一般而言，3-hop 检索半径也不推出全图 diameter=6；无向图中，同一中心半径 3 内的点对经中心路径至多 6，只是局部上界；有向图连反向可达性都未必存在。不能用这个推导解释当前 catalog 构建。

对八个缺失实体，当前证据还没有逐一分清：源数据里没有所需名字/别名，解析或语言/MID 过滤丢弃，提及片段不匹配，还是排序落到 Top-50 之外。**未知点应承认并用逐阶段记录查明，不能再称根因已修好。**

## 为什么之前没有解决，以及接下来改变什么

主要工程责任是：把几个不同的故障串成一条漫长主线；投入大量契约、审计和回归后，没有同步要求真实答案与失败漏斗发生可量化变化；还缺少足够可复用的实体链接/索引基础设施。防止错误答案和保留证据必要，但通过更多 guard 不能代替成功回答查询。我之前的优先级安排需要纠正。

这不表明 GrailQA 本身不可解决。源覆盖、实体链接、检索预算、输出约束和编译支持大多可通过工程验证与改进；GPU ECC 属于外部硬件条件。若确实缺少实体/事实的原始 artifacts，则需要取得正确数据，不能靠 prompt 或修改评估伪造覆盖。

下一步边界：

1. 保留现有 v1 与所有失败记录；停止 unchanged rebuild。先输出八个实体的逐阶段原因表、四个 retrieval 损失与一个 prompt 损失，不以再跑一次模型作诊断替代。
2. 复用已有解析结果与候选账本；若必须访问源记录，先选择谓词投影/现有索引/已有缓存。确需全扫时明确一次扫描要获得的可复用产物，记录每阶段时间与吞吐，不能为每个小修补各扫一遍。
3. 优先评估 [Pangu](https://github.com/dki-lab/Pangu) 的公开实体链接/ontology/执行组件和 [Freebase-Setup](https://github.com/dki-lab/Freebase-Setup) 的数据服务 artifacts。源码或下载链接存在，不等于 artifacts 已取得、版本匹配或已在本环境运行。
4. gold 可在隔离的评估侧用于定位“漏了哪个 ID”，但不能把这些 ID 回填 inference catalog、帮助候选排序，或据此选择部署事实。开发 18 题已暴露，不能作为未见测试集；原 frozen150 的 120 train-source + 30 dev-source 也不是完整官方 test leaderboard。
5. 同时推进已有真实 Neo4j/Fuseki 上的固定语义 CPU 实验。保留 FinBench 与 GrailQA 两个已选主数据集及全部 EQ1–EQ5 义务，显式列出未支持/未覆盖单元；不凭通过的单元重新定义研究问题。

## 已经可以汇报的实验结果

**FinBench-derived SF0.1 已有一项经过独立准入的正式物理实验。** 22 个测量 block、1,888 次计划执行；统计推断单位是 32 个已见家族的 held-out query，另有 16 个独立冷家族描述单元，不能把 1,888 次运行当独立样本。

| 观察 | 数字 | 能支持的结论 / 限制 |
|---|---|---|
| 已见家族，含当前查询计划选择成本的时间比 | XGAP / 双计划实时 profiling = 0.3096；95% CI [0.2509, 0.3683]；paired randomization p=9.9999e-06 | 此人群中避免当前查询双 profiling 有明确成本收益，约少 69% 时间 |
| 物理赢家选择准确率 | 30/32 = 93.75%；frontier Jaccard 0.96875 | 是物理路线选择质量，不是 NL/答案准确率 |
| 强简单基线 | fixed-A 与 family-global 选择、准确率和 regret 相同 | 尚未识别实例级 memory 带来的额外优势；不能只挑 profiling 当对手 |
| 冷家族 F3 | 默认 fallback 0/16；profiling 与 fixed-B 16/16 | 明确泛化负结果；描述性，不外推冷启动统计推断 |

以上引用仓库记录的已准入统计，本次没有重新读取全部原始计时并重算置信区间。见 [当前状态中的正式结果](../status.md) 和 [原有研究问题/数据范围](research_question_dataset_coverage_v1.md)。这是 FinBench-derived 的自定义异构查询协议，不是官方 FinBench conformant score。

另可报告真实 Freebase 三方答案一致性与 GrailQA 18 题覆盖漏斗；它们分别是执行正确性与失败诊断，不是竞争性 SOTA 问答结果。

## 待测指标及 research story

主假设：**在语义不完整或有歧义、后端异构且是黑盒的条件下，联合选择“获取哪些信息”和“怎样执行查询”，能否在满足硬约束、维持相当答案质量的同时降低整体代价？** LLM、catalog、ontology、后端探测是可选择且计费的工具。只证明能连接两个数据库，或只证明少调用模型，不足以证明这个假设。

以下 EQ1–EQ5 沿用白皮书，不重命名已冻结的 FinBench RQ-P1/P2/P3。正确性是所有性能比较的前置条件。

| 实验 | 必测指标 | 控制与对照 | 该实验要回答的研究问题 | 当前证据 |
|---|---|---|---|---|
| 正确性前置门槛 | 支持算子/组合覆盖、完整答案一致率、硬约束违规数、unsupported/timeout/failure 比例 | 独立参考求值、完整单库、原生两引擎；拒绝也进入分母 | 路径方向、身份、类型、映射和数据移动是否保持语义？ | 有限片段真实通过，非全覆盖 |
| EQ1 语义质量 | rank-1 结构解释 EM、答案 EM/F1、candidate Recall@K、joint reachability、可执行率/完整成功率、调用/修复/token 成本 | 同候选同预算 top-1；外部 KBQA 端到端对照另列；可达/不可达、支持/不支持分层且保留总分母 | ontology/约束选择是否比只相信模型分数更可靠？ | GrailQA 负 pilot；FinBench 公共语义实验缺失 |
| EQ2 有界放宽 | ε 扫描的 precision–recall–cost 曲线、返回候选/答案数量、硬约束违规、相对完整参考的遗漏/误收、ε=0 结果 | 不放宽、相同候选集与相同预算的排序；独立语义参考，固定 ε 网格 | 是否能用可解释的软约束放宽换取覆盖，并保住硬语义？ | 两数据集正式曲线均缺失 |
| EQ3 规划效率 | 展开/保留/剪枝状态数、规划时间、峰值内存、信息获取次数、最优可行方案保留率/代价 regret | no-pruning、预算内穷举小实例、no-information/no-memory/family-global/fixed routes | 少搜索是否仍保留好计划？获取信息是否值其成本？ | 有实现/小规模参考测试，跨数据集配对消融缺失 |
| EQ4 执行效率 | selection+serving 总时间、planning/serving 分解、median/p95、网络字节、远程调用、intermediate rows、吞吐/失败率、延迟与字节 regret | fixed-A/B、current profiling、集中式、匹配范围的 FedUP/FedX/HeFQUIN；同一解释、同数据/答案 | 更好的跨库放置、数据移动与信息获取决策能否产生实际收益？ | FinBench 部分正式结果；GrailQA 完整物理比较缺失 |
| EQ5 鲁棒性 | 随 ontology 缺失/噪声、映射缺失、端点能力变化的质量/成本曲线；成功率、显式拒绝、硬违规；分布外单列 | no-ontology、错误/部分映射、无自适应策略；相同扰动种子/强度 | 系统能否适应信息不完整，而非只在完整干净目录中工作？ | 两数据集正式结果缺失；F3 是另一个冷家族维度 |

catalog 的 build time、吞吐、磁盘/RSS、更新成本与 grounding Recall@K 应进入基础设施诊断；不能把它們单独当作整篇论文的核心贡献。离线建库/训练成本与在线查询成本分别报告，再给出预先声明查询量下的摊销值。LLM 延迟、tokens、后端探测和失败尝试必须计入相应端到端预算；不能把最昂贵的 acquisition 移到计时区间外。

有限实例验证不能推出一般 ε 保证、sound/complete pruning 或全局最优性定理。若论文要提出这些理论主张，仍需明确前提、语义定义和独立证明。

## 可复用的强基线：没有一个方法直接覆盖全部指标

“SOTA”随数据、模型、训练与硬件配置改变。这里列官方代码可查的强/近期基线，并不声称每个都是截至今天的 leaderboard 第一，也未声称已在 XGAP 环境复现。

| 方法与一手来源 | 最适合比较什么 | 接入/公平比较边界 |
|---|---|---|
| [KBQA-o1，ICML 2025](https://proceedings.mlr.press/v267/luo25d.html) / [官方代码](https://github.com/LHRLAB/KBQA-o1) | agentic KBQA、MCTS 搜索、EQ1 与 acquisition/search cost | 需要模型与 Freebase 服务；端到端系统对比和同 backbone 的策略消融分开；不能用其整榜数字对比我们的 18 题 |
| [KBQA-R1 官方代码与发布模型入口](https://github.com/sunxin000/KBQA-R1) | 近期强化学习 KBQA、GrailQA 语义/答案质量与工具步数 | 优先核验已发布 checkpoint，而非另建大规模训练任务；模型/训练差异不能归因于 XGAP 规划策略 |
| [Pangu](https://github.com/dki-lab/Pangu) / [模型说明](https://github.com/dki-lab/Pangu/blob/main/trained_models.md) | 成熟 grounded parsing 对照，实体链接/ontology/执行组件复用 | 历史依赖及 endpoint 需要适配；可复用基础设施不等于新的测试集无泄漏 |
| [FedUP](https://github.com/GDD-Nantes/fedup) / [实验代码](https://github.com/GDD-Nantes/fedup-experiments) 与 [RDF4J FedX](https://rdf4j.org/documentation/programming/federation/) | CPU 可运行的 SPARQL 联邦 source selection、计划、远程调用与性能；EQ3/EQ4 | 在匹配的 RDF/SPARQL 联邦子轨比较；不能假定原生支持我们的 Neo4j Cypher 放置，转换/适配成本要单列 |
| [HeFQUIN](https://github.com/LiUSemWeb/HeFQUIN) / [mapping 实验](https://github.com/LiUSemWeb/HeFQUIN-VocabMappingsExperiments) | 异构数据访问、映射与联邦计划开销；EQ3/EQ4，部分 EQ5 | 公开 mapping 实验不自动等于噪声 ontology 或 ε 放宽实验，也未核验原生 Neo4j 支持 |

EQ2、剪枝正确性和 noisy ontology 等贡献尤其需要 XGAP 自身明确的消融与参考求值；不能找一个不提供同等功能的系统，便宣称全面胜出。所有主实验仍需覆盖两个已选主数据集，协议缺口应先显式绑定，不把可用外部基线当作更换数据集的理由。

## 可验收的排期，而非效果承诺

以 2026-09-10 的已知状态估计，以下是工程目标和前置条件，不是已执行完的实验，也不保证出现正面结果：

| 时间窗口 | 应交付的具体产物 | 依赖 / 失败时的产物 |
|---|---|---|
| 现在 | 本报告：已测 FinBench 正/负结果，真实执行范围，18 题失败漏斗，完整指标缺口 | 已有记录可汇报，不必等 GPU |
| 未来 1–2 天（目标 9/12 前） | 支持片段/真实数据覆盖矩阵；catalog 8+4+1 逐阶段原因表；不依赖 LLM 的 CPU 测试/实验入口与明确比较协议 | 所需源记录若缺失，列出具体不可取得的 artifact 与受影响单元；不再无目标全扫 |
| 未来 3–5 个工作日 | 第一版扩展 CPU 结果表：正确性、fixed/profiling/centralized 与至少一个范围匹配外部基线的试运行；随后按冻结协议重复 | 当前数据/endpoint 可用；基线接入失败同样交付错误与缺口，不能伪装完成比较 |
| 模型 endpoint 和独立事实覆盖两者具备后 1–3 天 | 第一次真实 NL → native answers 的开发结果，全部问题有终态与分层原因 | 18 题是开发结果；不是 frozen150 正式表或 SOTA 结论 |
| 完整首轮双数据集 EQ1–EQ5 | 目前只能按约 2–4 周工程量作初步预算；上述前两项完成后重估 | 取决于语义/事实覆盖、外部 baseline artifacts、缺失 query structures 与测量基础设施；不作为达标日期承诺 |

现在没有充分证据给出“某日所有设计指标达标”的可信日期。可承诺的是以明确产物推进并如实报告负结果，不能承诺 memory 优于 fixed route、ontology 提升准确率或 SIGMOD 级效果一定成立。下一步必须用实际答案、范围覆盖、比较表的进展验收，而不再以增加多少测试或完成多少审计层作为研究进展的替代指标。

## 统计与解释边界扫描

本次按 ARS 清单检查 11/11 类风险；“检查”不等于凭报告就排除了风险，未重算原始统计的地方明确保留未知。

| 风险 | 本次检查结论 |
|---|---|
| Simpson's paradox | 已见 F1/F2 与冷 F3 必须分层；未对原始逐家族计时重算，不能声称已排除所有组内/总体反转 |
| Ecological fallacy / 单位错置 | 32 query 才是正式推断单位；1,888 次重复不是独立样本；不能推广到所有 KGQA |
| Berkson / 选择偏差 | 18 题与 frozen150 是选择的开发/研究子集；不能当官方测试分布；固定“通过题”会造成偏差 |
| Collider bias | 只在编译成功或 prompt 可达的题中比较可能引入条件选择；保留总分母并将条件切片另列 |
| Base-rate neglect | 93.75% 是物理赢家选择率，非答案正确率；同时保留 0/16 冷家族、5/18 可达性等分母 |
| Regression to the mean | 不把挑选出的失败题在修补后的变化直接当总体收益；新测量仍需同输入配对比较 |
| Survivorship bias | 超时、provider/grounding/硬件失败不能悄悄丢弃；最新失败部署没有成功题目结果 |
| Look-elsewhere effect | 现有正式次级对比有 Holm；新 EQ/ε/扰动网格尚需冻结，不能只选胜出的指标 |
| Garden of forking paths | 保留旧协议、零增益 catalog 与失败记录；新接口/目录/硬件版本分别记录；不得事后缩小 RQ |
| Correlation / causation | 0.3096 相对 profiling 的收益不能归因于实例 memory，fixed-A 同选择；两次 catalog 构建耗时不能做单因素因果解释 |
| Reverse causality | 当前有前置计划选择时序与冷家族独立定义；本次未重审全部原始训练/计时记录，不能增加新的因果或无泄漏保证 |

综合状态：已记录的 FinBench 主效应在其冻结范围内可报告，但整体证据解释为 CAUTION；新语义、泛化、ontology 与全部系统效应仍待实测。本文不替代原正式结果的独立准入。
