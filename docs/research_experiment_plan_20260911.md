## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: plan, based on existing approved research scope
- Origin Date: 2026-09-11, Asia/Shanghai
- Verification Status: SOURCE-INSPECTED PLAN; proposed experiments and algorithms
  below are not completed results
- Version Label: research_experiment_plan_20260911_v1
- Implementation checkpoint: 7aad1dc (T3-B observation memory accepted)
- Authority: latest user instruction: research-oriented prototype, RQ-led
  engineering, efficiency/effectiveness/scalability, Ptime planning with bounds,
  small-data development, new real results by September 18

**Subsequent execution:** P1 local-option planning is implemented and its first
model grid/native slice completed. The retained6.33x heuristic regret case was repaired by terminal-source admission;
150 affected replays and70 reused oracles verify the correction. See
[P1 correction](report/polynomial_terminal_correction_20260911.md). Ordinary-entry
one-request refresh/pre-execution reselection is now accepted at A1; see
[A1 evidence](report/semantic_refresh_20260911.md). Its single controlled native
observation favored no-refresh; no performance claim is established. Execution-prefix
adaptation and acquisition stopping/value policy remain distinct gaps.
Statements below describing the initial missing implementation are historical
planning context, not a claim that the replacement is still absent.

## 1. Research question and proposed contribution

**主问题：面对语义尚未完全绑定、统计信息不完整的异构黑盒图源，如何联合决定
信息获取与联邦执行，在硬语义约束和预算下，用较低的总成本获得正确答案？**

这延续既有 agentic architecture，不把研究改成 catalog construction、单纯
GraphRAG 或通用数据库产品。论文的潜在 X-factor 是**代价可见的选择性信息获取
与执行决策的联动**：是否值得查 ontology、澄清、调用模型、profile，何时已有
信息足够执行，何时旧观测不适用。这是待检验的贡献假设，尚不是已证实的优势。

三个贡献支点必须能分别描述、实现和反驳：

1. 语义与物理选择隔离：硬约束落实到可执行的有界 semantic program；降低
   代价不能偷偷改变问题含义。LLM负责提出解释，确定性核心负责验义、编译和执行。
2. 选择性 acquisition：把获取信息本身的耗时、调用和 tokens 计入当前查询或
   明确的历史摊销；与全量探测、完全不探测及简单固定路由直接比较。
3. 可描述的 Ptime planning：明确能精确求解的子类；其余启发式给出适用的解质量
   界/证书和反例，测量界的松紧及真实 regret。不能仅用候选截断宣称可扩展。

仅证明“memory hit省了profile”不够。已有FinBench结果中fixed-A与family-global
和memory选择相同，尚未隔离实例memory收益；冷家族还有0/16的负结果。新实验
必须包含这些强简单对照及cold/stale条件，不能围绕已有正结果重写主张。

## 2. X-factor / Y-factor 与可反驳假设

这里同时区分 **X-factor（贡献机制）** 与 **X变量（操纵因素）**；Y变量是结果。
以下R-E/R-C/R-S是本次实验组织标签，保留历史EQ1–EQ5与RQ-P1/P2/P3原编号。

| 研究问题 | X：主要因素与对照 | Y：主指标；辅助指标 | 支持什么结论；如何被反驳 |
|---|---|---|---|
| R-E Effectiveness（EQ1/EQ2/EQ5）约束与信息获取是否帮助得到正确、可执行解释？ | 相同模型/grounded候选/预算下，完整语义策略、model-confidence top1、schema-only、no-ontology；ambiguity、目录缺失/噪声、软约束ε | 主：answer EM/F1及正确完成率；辅：meaning match、硬违规、候选Recall@K、joint reachability、澄清/失败率、tokens | 质量收益来自约束/信息而非模型或更多预算；若只提高可执行率而答案错误，不支持主张 |
| R-C Efficiency（EQ3/EQ4）何时获取信息值得其成本？ | 完整策略、固定A/B、无memory、全量profile、无profile/probe、无replan、family-global；cold/warm/stale分别报告 | 主：含acquisition的配对E2E时间比；辅：规划/获取/执行分解、calls、bytes、rows、选择regret、质量 | 节省总成本且不损害语义/答案；若固定路由相同或计入获取成本后优势消失，应明确报告 |
| R-S Scalability（EQ3/EQ4）随着图与规划输入增长能否保持可用？ | 分开改变图规模N/E、源数k、源算子m、显式路径展开大小h、并发c；比较Ptime planner、静态路由、小规模穷举oracle | 主：planning time/RSS对m,k的曲线，以及E2E/成功率对N/E的曲线；辅：候选/观测数、p95、吞吐、解质量界/实测regret | 多项式规划不等于查询输出或后端执行为多项式；若只有固定小m下的数据曲线，不能声称规划可扩展 |

**控制变量**：数据及副本完整性、语义/答案、模型checkpoint与生成预算、机器/服务
版本、timeout、并发、缓存状态、统计训练split。物理实验输入同一gold或已固定解释，
不让方法间LLM随机性混入planner效果；NL端到端轨单独评价。人工网络延迟/漂移作为
明确干预单列，不冒充自然生产负载。

## 3. 实验清单：每次运行先绑定ID

| ID | 目的与输入 | 运行前门槛 | 输出及完成条件 |
|---|---|---|---|
| DEV | 冻结极小图、现有完整gold chains；两条测试链 | 当前修改涉及的模块与接口 | 局部正确性+一条相关完整slice；不产生论文效果结论 |
| P1 | planner数学模型、局部选项、微型oracle及规模输入；不访问模型/大数据 | planning_ptime_contract_v1，算法和假设先冻结 | 伪代码、复杂度、证明/适用界；小实例与穷举比较、边界反例；Ptime实现接入正常路径 |
| LINK | 五题真实Qwen响应接到已有真实Neo4j/Fuseki小图 | 3804011真实产物和版本核对 | 每题唯一终态、实际输出及gold对比、完整调用账；跨机器分阶段时间单列 |
| INT | 已冻结真实数据协议的小型集成切片 | DEV完成、预建数据/catalog可读 | 真实schema/identity/source/typed answer接线；预选ID及所有失败保留，不以成功题选样 |
| E1 | 两个主数据集的语义与答案比较 | 冻结候选/推理视图/参考与执行接口；不把gold放入inference | R-E主表及stage funnel；当前150题语义-only旧runner须扩展执行侧，不能称已具备答案F1 |
| E2 | 同一语义、真实图源的总成本比较 | 相同方法可执行范围、真实计时/调用账 | R-C配对主表，冷/热/旧观测分层；shared candidate validation移出测量块 |
| E3 | 必要单因素消融：memory、acquisition、replan、ontology/pruning | 对应能力确实被方法入口调用 | 每项消融仅改变对应机制；缺接线即报告缺实现，不靠改标签生成full-agent |
| E4 | planner规模与真实图规模分开扫描 | P1与INT；每个规模先一次答案校验 | R-S曲线、超时/失败曲线、界与oracle差距；逻辑端点模拟与真实端点数分开 |
| E5 | ε和缺失/漂移的质量—成本曲线 | 固定扰动种子、硬/软约束定义 | EQ2/EQ5；ε只约束声明的语义距离，不能推导答案F1保证 |
| EXT | 外部方法对照 | artifacts就绪并有匹配语义/部署轨 | 同数据/预算重跑；未复现就列缺证据，不能拿原论文整榜数字直接相减 |

P1的拟定离线规模网格：m∈{2,4,8,16,32}，k∈{2,4,8}，固定显式局部IR；
仅在k^m≤4096时运行穷举oracle，每个小cell使用固定10个种子。大cell只运行
多项式算法，不生成指数个候选再截断。计数与实测计时分开，模型输入不是数据图。
资源预算固定后再运行，未实现入口不得先捏造命令/结果。

E4图规模沿已有FinBench协议SF0.1主轨、SF1历史条件项；Freebase沿已版本化快照
与冻结输入清单扩展。具体load/artifact可用性仍需INT核验，不启动大数据debug。
正式因素网格在pilot成本可知后、查看正式结果前另存版本；本文件不覆盖已冻结协议。

## 4. Population、统计和成本边界

- 保留FinBench SF0.1的32个seen-family query和16个cold-family描述单元，以及
  GrailQA frozen150的历史样本清单；后者不是完整官方test榜。18道暴露过的开发题
  不变成未见测试。两个主数据集的EQ1–EQ5缺口保持可见，不把缺失单元标N/A。
- FinBench增加NL的部分必须标为人工构建的FinBench-derived问句，并独立核对gold；
  原benchmark数据存在，不等于已有官方自然语言问答集。
- 性能按query配对，在block内平衡/交错方法顺序。重复执行先在query内聚合；
  不能把成百上千次重复当作独立样本。沿原协议用query-level bootstrap区间，
  冷家族描述性单列。新增family共享因素使用family/block聚类分析，不夸大样本量。
- 同时报告全体终态与成功条件下延迟；失败、timeout不能从总分母中删除，也不能
  给失败填0ms。未完成执行按截止时间截尾并报告完成率；p95小样本仅作描述。
- 首要成本是查询进入到终态的wall clock；分解项要按实际时间轴解释，并行阶段
  不能相加冒充wall time。LLM/profile/sample/失败尝试计入；远程排队/数据准备另列。
- memory的历史获取费用按预先声明的使用次数摊销，同时报告冷启动费用；不能
  把warm snapshot当免费真值。各方法控制backend cache、warmup和validation污染。
- 论文图至少包括：质量与失败漏斗；含获取成本的时间对照及分解；m/k规划曲线；
  图规模曲线；必要消融；ε/漂移曲线。没有改善也如实画出，不追加搜参找正结果。

## 5. 基线如何匹配研究问题

第一层优先复用同backbone的固定A/B、model-top1、full-profile、no-memory、
family-global、no-replan；这是隔离XGAP机制所需，不能用弱默认路由替代。
小实例穷举oracle独立预算，报告其测量成本，不把其事后信息提供给在线方法。

外部联邦轨优先FedUP/FedX。FedUP是SPARQL federation、使用summary和source
selection；比较应在匹配的RDF子轨，不能假定它原生规划Cypher。summary构建亦属
离线成本。[官方FedUP实现](https://github.com/GDD-Nantes/fedup)

外部语义轨候选KBQA-o1，其公开工作使用agentic逻辑形式生成和MCTS。模型/训练/
工具条件不同，端到端系统对比与同模型策略消融分开；当前未复现，不能称XGAP已
超过它。[ICML 2025论文](https://proceedings.mlr.press/v267/luo25d.html)

## 6. “系统完整”的实验版定义及真实剩余

必须有真实可调用的方法路径，不能只有类型/API或用测试stub补缺失机制。完整性
是本论文声明范围内的闭环，不要求支持所有图查询语义或形成完整开源产品。

| 项目 | 当前状态 | 对本周实验的影响 |
|---|---|---|
| 有界语义、编译、双库执行、独立结果核对 | 已实现并有真实小图证据 | 保留现有profile；不再因一般语言扩展推迟评价 |
| Interpretation、LLM HTTP、离线catalog与普通query入口 | 已实现并接线；真Qwen验证仍待产物 | 属于缺真实验证；不能说没有LLM功能 |
| 同入口静态对照与精确上下文观测memory | 7aad1dc已实现/验收；5冷+5热程序正确 | 支持no-memory机制比较；不证明泛化或真实提速 |
| Ptime placement与可核验解质量保证 | **尚未实现**；现主入口枚举∏k_i | P1必须优先修复，旧枚举保留作小oracle |
| 选择性获取/执行中replan的普通路径 | 专用模块/runner已存在，普通入口未全部接通 | 若论文full-agent声称此能力，必须实际接线并做对应消融 |
| 两真实数据集的同语义、同代价比较与答案评估 | 旧专用管线存在，新路径有适配缺口 | INT/E1/E2的具体工程；不重写全项目或重建大catalog |
| 规模、外部对照、正面收益 | 多数属于缺实验或缺外部接入证据 | 不能用模块测试数量代替 |

因此“只差测试”不准确，但“所有模块都没有”也不准确。当前必做工程是P1、
研究方法接线、真实输入/评估接线及成本可比性。通用streaming、产品UI、自动发现
任意分区等保持边界说明，除非具体实验暴露它们成为阻塞，不主动扩项。

## 7. 一周交付顺序和停止规则

- 9月11日：本计划与算法规格；结束既有T3-B；等待五题模型LINK，继续P1离线工作。
- 9月12日：P1与必要策略接线在toy验收；INT及正式运行manifest/预算冻结。
- 9月13–14日：新增真实E1/E2主结果和必要E3；先获得完整结果表及失败表。
- 9月15日：E4、E5及已可用外部对照；不开展另一次大规模训练。
- 9月16–17日：分析、独立核对、图表和缺口报告；只重跑被具体缺陷影响的cell。
- 9月18日12:00北京时间内部交付目标：新增真实结果、协议/版本、可复现实验、
  结论及限制。期限不保证正面收益；外部失败不能伪装成功或把toy换名为evaluation。

每轮任务必须写明“修复哪个RQ的哪项实验阻塞、最小改动、哪条检查结束本轮”。
文档-only无需回归；代码只跑风险相关测试和tiny slice。全套回归不是milestone
默认动作。相同失败先本地replay，不自动重试外部动作；相同成功不反复复验。

本轮R0只修改研究计划、算法规格、Goal/工程规则与状态；不改冻结数据/gold、
旧正式协议、现有外部作业或增加大数据运行。R0完成不等于P1已实现或总Goal完成。
