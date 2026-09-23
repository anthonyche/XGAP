# Chapter 6: Experimental Study — Execution Plan

**2026-09-23 当前执行覆盖：**以[正式执行与五方法绘图合同](ch6_formal_execution_20260923.md)
为准：21 图不变，每图呈现 XGAP/NP/SH/GR/TS；F6 为五方法成本敏感性。
不适用参数保留固定实测参考，不支持部署/不可评分指标明确标记，不补零或编造曲线。
下方原始方案作为历史设计保留，不再据其方法子集或旧 N/D 上限发布新实验。

**2026-09-22 后续用户更正（优先于下方保留原文）：** Two-stage 表示外部方法串接，
不是内部 XGAP 变体；删除 LD。方法、预算及适用轨道以
[最新方法定义](decisions/ch6_external_twostage_20260922.md)为准。下方 §4.1 旧定义及
相应三方法乘数只作历史，不可据此执行。

2026-09-22. 对应统一 fixed-depth XGAP；本文件是实验设计，不是实验结果。与之配套的是 [查询结构与生成规范](query_structure_spec_20260922.md) 和 [coding agent 交接说明](coding_agent_brief_20260922.md)。旧控制器的测量不改名为新版结果。

## 1. 研究问题与章节结构

| RQ | 要回答的问题 | 主要证据 |
|---|---|---|
| RQ1 | 与两阶段方法相比，联合决策的端到端延迟和后端工作量如何？ | E1–E2；同时报告 F1–F2 的质量 |
| RQ2 | 查询歧义、候选规模和信息获取代价如何影响处理效率？ | E3–E4、E6–E8 |
| RQ3 | 允许未验证解释时，解释损失、答案质量与回答覆盖率如何变化？ | F1–F4；配套运行记录中的耗时与覆盖率 |
| RQ4 | 探测、前瞻及执行代价估计如何影响决策质量与规划开销？ | E5、F5–F8 |
| RQ5 | 候选规模、后端数量及数据规模增加时，规划和执行如何扩展？ | S1–S4 |
| RQ6 | 一次真实运行中，观测如何改变后续物理计划选择？ | C1 与 T1 |

正文：6.1 Experimental Setup；6.2 Efficiency；6.3 Effectiveness；6.4 Scalability；6.5 Case Study；6.6 Summary。Setup 内使用 `\stitle{}`，不增加三级编号。

保留 **8 个效率图单元、8 个效果图单元、4 个扩展性图单元、1 张案例图和 1 张案例表**。S1–S4 放实验附录，6.4 总结主要观察。E/F/S 是设计 ID，不是论文 Figure 编号；同一数据集的重复面板不冒充新实验。

## 2. 数据与部署

### 2.1 三个领域，共同实验协议

| ID | 冻结的数据组合 | Neo4j 内容 | Fuseki 内容 | 跨源键与真实性 |
|---|---|---|---|---|
| D1 | SNB-derived | 生成的社交关系、消息与行为 | 从同一 SNB 快照分出的属性、地点、标签和组织关系 | 保留原始 ID；不把生成的人物与 DBpedia 人物按姓名强行对齐 |
| D2 | IMDb–Wikidata | IMDb TSV 转换的作品、人物、参演关系与评分 | 冻结 Wikidata 子集中的类型、奖项、国家等属性 | 用经核验的 IMDb ID（P345）桥接；歧义或缺失映射单列 |
| D3 | FinBench-derived | 账户、转账、金额和时间等业务事实 | 从同一快照分出的公司、账户所有权、媒介属性；必要时增加明确标记的受控风险注释 | 原始 ID 精确映射；自建风险注释不称 Wikidata 的真实风险标签 |
| D4 | Synthetic stress supplement | 参数化生成 | 同一生成快照的 RDF 分片 | 仅补充 S1–S4 的极端规模，不代替 D1–D3 的实验 |

这是对三类 workload 的设计命名，不表示它们已经装载。SNB/FinBench 的生成实体不天然对应外部真实人物或公司；默认采用可验证的同事实分区。DBpedia/Wikidata 的额外连接只有在存在可核验标识时才纳入，并记录映射来源；不为保留数据集名字生成假的 `sameAs`。D2 的许可条件须在下载和发布前核对，优先发布转换脚本、版本和 ID 清单。

数据容量目标：D1、D3 约 10^6 条边，D2 约 10^7 条边。先检查现有快照和磁盘，再冻结 scale factor、抽样规则及实际顶点/边/三元组数量，不为凑整数截断查询结果。正文表只填装载后的真实数量。

FinBench 使用固定版本的生成器、规范及只读模板；不运行金融写事务。IMDb 仅用获准的下载文件；不抓取网页替代数据接口。所有远程知识库内容先冻结为本地子集，计时实验不查询公共 Wikidata/DBpedia endpoint。

### 2.2 运行轨道

- **NL native 主比较**：相同 NL 请求 → Qwen API/初始化 → 实际获取、规划和 Neo4j+Fuseki 执行。用于 E1/E2/F1/F2，保留 W1–W4 分层。
- **Controlled native 机制实验**：相同、事先冻结的部分查询、候选族、初始证据和快照；在线算法不知道私有意图。用于参数、消融和规模实验，计时从公共初始状态开始，不称 NL 端到端耗时。
- **Matched RDF 外部方法比较**：仅用于只支持 RDF 的原版方法。将相同查询相关事实无损表示为 RDF，所有参赛方法用相同源、键、结果语义和资源。结果与 native 分开，不能跨部署算 speedup。

E1–F8 与 S1–S4 在三个领域运行同一协议和共同可支持的扫描水平。不是“一个数据集说明一个问题”。D4 只增加高规模检查。W1/W2 的单源性能不用于宣称跨源收益。

## 3. 查询、样本与答案

### 3.1 Workload 分层

| 层 | 位置 | 未验证选择 | 用途 |
|---|---|---|---|
| W1 | 单源 | 无语义歧义 | 测量额外规划开销；执行统计仍可不完整 |
| W2 | 单源 | 实体 | 分离实体获取与 federation 的影响 |
| W3 | 跨源 | 实体、谓词/聚合解释 | 主研究场景 |
| W4 | 跨源 | 多字段，包括逻辑源范围 | 检查较复杂的联合决策；副本选择不是语义歧义 |

结构、歧义和物理信息状态分别记录；不能把 W1–W4 的差异当成只有一个因素的因果实验。

每数据集每层 **200 个 query–intent cases 是正式集的初始目标**，共 `3 × 4 × 200 = 2400`，不含 D4、参数扫描和重复运行，也不代表 2400 个独立结构。每层先在独立开发集做 20–30 个 case 的 pilot，估计配对波动及资源开销，再冻结样本量、重复次数和全研究预算。200 不是已完成的功效分析；预算不允许时，在正式测试前明确缩小可支持的结论。

尽量每层覆盖至少 10 个不同的规范化模板族，再采样参数；结构不足时报告实际族数，不把改一个实体算新结构。开发/测试按规范化模板族与派生来源分组，避免同一模板的改名版本跨集。置信区间按模板族聚类，重复运行不增加独立样本数。

### 3.2 构造与参考答案

执行 [查询规范](query_structure_spec_20260922.md)：保留类型化结构及输出语义，生成合法具体查询，隐藏指定字段形成歧义请求。模板合法性和样本选择在比较方法运行前确定。

每个 case 保存 NL、完整 gold query、来源快照、映射、候选族、验证要求、loss 权重和独立参考答案。gold 与 reference 由离线 evaluator/私有模拟用户持有，不能进入模型 prompt、成本估计器或在线动作生成器。自然语言表达须描述固定要求；不能把模型遗漏的要求事后补成“原本未说明的 gold”。

候选覆盖确认只返回所提交族是否包含意图，不返回哪个候选正确。模拟用户按被冻结的 gold 回答请求字段，记录实际调用和披露字段数；等待时间是模拟服务延迟，不称真人响应时间。受控族先等概率取模板族，再在合法不同意图中等概率取一个；抽样分布不自动成为 planner 的概率模型。

参考答案应由独立的完整查询执行或单独的关系计算实现取得，不只对比同一个 XGAP 编译器的两种运行。保留正确空结果；不根据某个方法成功或 XGAP 获益筛题。记录空结果比例、原始拒收数与原因。FinBench 路径重复、边 ID、时间递增和截断规则必须进入 gold 语义，不能偷偷用 LIMIT 降低执行工作。

## 4. 方法与公平性

### 4.1 主比较与消融

| 名称 | 精确定义 | 分类 |
|---|---|---|
| XGAP | 统一 fixed-D 在线控制器；共同验证与 loss 条件；信息获取、单步物理变换和执行联合选择 | 本文方法 |
| Two-stage | 语义阶段只按获取代价选择绑定动作，达到与 XGAP 相同的语义执行条件后固定一个合格候选；再使用相同物理编译器、变换、metadata/probe 权限和执行器 | 共享组件机制对照，不是外部 SOTA |
| LLM-direct | 同一 Qwen API 一次产生完整候选，接相同物理规划器；不增加自动纠错、gold 修补或额外重试 | 自建直接生成对照，不是已发表外部方法 |
| XGAP-noProbe | 只移除统计 probe，保留 metadata、物理变换及同一完成保护 | 消融 |
| XGAP-shallow | 与 XGAP 相同，但 D=1 | 消融；与深度扫描 D=1 复用记录 |
| XGAP-greedy | 使用同一动作集、有限观测、资格检查及完成保护；非终端动作只比较即时估计代价，不计后续执行代价；终端保留其执行代价，按同一规则打破平局 | 明确定义的 myopic 消融，不能简称“最优即时收益” |

Two-stage 的语义阶段使用与 XGAP 相同的预算、绑定动作及固定深度，不调用“最优澄清 oracle”。在合格候选之间用预先冻结且不含执行代价的排序选一个。若当前实现仍无条件询问所有字段，应先实现上述停止合同，不能据更弱的实现归因联合收益。保护完成所用的内部全字段请求不是新增的 Full clarification baseline。

LLM-direct 无验证地选择解释，不能声称满足 XGAP 的资格保证。它的拒答、非法输出和错误结果均进入质量分母；只比较速度不构成等质量优势。模型看到的公开 schema/catalog、源标识和映射与 XGAP 相同；不得给它 gold，也不得剥夺执行所必需的公开接口。一次生成的是可表达跨源查询的结构化完整请求，不假装一条 Cypher 能直接查询 Fuseki。

主实验默认比较 XGAP、Two-stage、LLM-direct。三种消融只在指定组出现，不把所有方法乘入每个扫描。严格验证 `Lambda=empty` 可作为同一算法的补充设置，不恢复两章、两个独立算法的说法。

### 4.2 原版外部方法

优先核对已有的原版 ARUQULA+FedUP 组合。固定作者版本、prompt、解码和默认行为；只做必要接口/环境接入，不实现“Robopt 风格”后称之为 Robopt。未核验竞争范围，不称该组合 SOTA。

原版方法只有在同事实 RDF 或其原生支持的单源 RDF 条件下参与比较。每个数据集先列 `supported / unsupported / setup_failed / timed_out / answered`。算法不支持的跨平台组合不画柱，不记成零耗时；运行时失败保留在已定义适用集的全分母中。不得逐题删除失败方法以制造成功子集。

若原版组合通过准入，发布 E1/E2/F1/F2 的 **matched-RDF companion panels**，同一部署上重跑参赛的 XGAP 和共享组件对照。若未通过，保留支持表和原因；内部 Two-stage 不能被改名来填补外部比较。2026-09-21 工程记录中原版组合的 VALUES 支持失败是需核对的已有证据，不授权修补作者算法或重复旧作业。

## 5. 环境、成本与默认参数

### 5.1 环境

确认项：Neo4j、Fuseki；Qwen 27B 通过 **API** 调用。其余环境参数从实际部署清单填写。Coordinator 使用实际实现语言和进程；模型服务位置、排队与传输延迟均记录，API 等待计入 NL 请求耗时。

冻结 endpoint 标识、请求 `model` 字符串、服务返回的模型标识（若提供）、temperature、token 上限、超时、并发、重试、prompt/hash 和调用日期。不写凭据。`27B` 是用户给定的服务名称/规模描述，不据此编造 checkpoint 或推理硬件。代码中已有 32B/其他模型配置不得自动代用。

LLM tokens 在文字或环境表中报告每请求平均输入/输出及实际调用数；未知为 null，不记 0。不额外占用实验图。受控实验复用冻结初始材料，实际 API token 数为 0 时标明这不是 NL 轨道。

### 5.2 Pilot 起点，不是已冻结的正式配置

| 参数 | 起点/扫描 | 约束 |
|---|---|---|
| D | 默认 2；扫描 1,2,3,4 | 每个配置中固定；不以 D=10 作为 PTIME 结论的依据 |
| H | 默认 12；扫描 2,4,8,12,16 | 包括绑定、metadata、probe、物理动作；不只计澄清 |
| N | 默认 8；主扫描 8,16,32,64 | 全部是合法不同候选，构造前检查大小；u=3 的二值独立字段只有 8 种组合 |
| u | 默认 3；扫描 1,2,3,5,8 | 沿用第四章 u=\|U(Qcirc)\|，即部分查询中的未绑定字段数；不是运行中的未验证字段数 |
| K | 默认 4 | 保留受保护种子；实际计划数另报，不能拿全局注册表大小当每查询 K |
| epsilon | 默认 1/3；扫描 0,1/6,1/3,1/2,1 | 初始三个字段等正权；固定 loss 定义，不随方法/结果改权重 |
| Lambda | 冻结的允许未验证字段清单 | 默认不含硬约束或固定源要求；epsilon=0 不自动等于强制逐项验证 |
| 成本 backup | 默认 worst-case | 若使用 expectation，须对全部相关动作提供独立冻结的概率模型并单独命名配置 |
| 获取价格比 | 0.1,0.5,1,2,5 倍冻结基准 | 只改指定类动作的声明价格，不称真实服务变快 |
| 单 backend timeout | 60 s 起点 | 所有共享组件方法相同；原版方法保留作者行为并加相同外层请求预算 |
| 每请求 backend calls | 100 起点 | 包括实际探测与最终执行；请求总时限、lookahead 时限、内存与全研究 API 预算由 pilot 后冻结 |

三个等权字段的非零 Hamming loss 最小为 1/3。扫描跨越这些可达值，并保留一个小于 1/3 的水平作为区间内对照；同一离散区间中的相同结果不表示方法没有权衡。若应用另定权重，先冻结权重，再据可达 loss 值选择水平。

N、u 不是任意独立参数。N 扫描固定 u，只使用有足够合法取值的预注册字段域。u 扫描从相同完整查询模板中隐藏不同数量的真实字段，固定 N、图结构、loss 的完整坐标及权重；某水平没有足够合法取值时不强补网格。无法保持这些条件的水平单列为匹配 cohort，不称纯字段数的因果效应。不能用重复候选、无意义字段或截断后重算 loss 补齐网格。

保持编译器和语义/预算检查不变。较大 N/源数的序列化和缓存上限若尚未通过工程检查，先修复容量合同并重新冻结版本；拒收/资源截止须报告，不能偷偷删点或放宽约束。

## 6. 指标、分母和运行协议

- **NL end-to-end latency**：接收请求至结果物化或显式失败，含 API、初始化、在线规划和执行。成功耗时图只比较共同返回完整结果的 case，标明该集合大小；所有请求的成功/错误/超时另表，不把快速失败当提速。
- **Controlled request latency**：公共初始状态至物化；与 NL 耗时分别命名。阶段计时使用互斥或清楚标注的嵌套口径，不把并行等待重复相加。
- **Backend calls**：实际 source API 请求，区分 probe/metadata/执行；所有尝试均计入，包括最终失败。adapter 调用和 HTTP 重试次数分别记录。
- **Correct-answer rate**：完整答案满足 gold 的类型、集合/多重集、顺序及聚合语义的请求数 / 全部适用请求。失败/拒答为未正确完成；正确空结果为成功。
- **Answer coverage**：返回完整、可评价答案的请求数 / 全部适用请求；错误答案仍属于已回答，不与正确率混用。
- **Answer F1**：按冻结的完整 typed rows 计算集合/多重集 F1，失败记 0；不能替代排序和数值聚合的严格正确率。空-空=1、仅一侧为空=0。
- **Interpretation loss**：独立计算 d(gold,selected)，并另存 rho 与 epsilon。它不是 answer F1；执行失败但选定查询可解析时可记录其解释损失，主返回答案统计与之分开。族外/不可映射输出记不可评分及原因，不丢出正确率分母。
- **Certificate audit**：对返回答案检查 `d <= rho <= epsilon`、验证要求及物理语义；违规计数和不可评分数单列。最大实测 loss 小不等于证书计算正确，更不代替定理。
- **Trace cost in work units**：用所有方法共用、预先冻结的非负权重，对实际动作与终端执行消耗的已记录资源计价，例如调用、披露字段、传输字节和 CPU 时间。不能用每种方法自己的 terminal estimate 当作效果分数；估计成本另存日志。缺失资源不按零填入，正式运行前冻结可测资源及权重。该量不是实测 ms 或货币，初始化不计入从 s0 开始的 trace cost。
- **Planning**：CPU/wall、扩展状态、编译、certificate、fallback 和 cap-hit；内存为 coordinator 的峰值 RSS，与计划序列化字节分开。

请求按预定种子随机、交错方法顺序，固定服务并发与缓存。主表使用一个明确的缓存协议；不把 XGAP 热缓存与基线冷缓存比较。重复次数由 pilot 后冻结，保存每次结果而非仅均值。配置间比较用相同 case 集、意图和快照；置信区间按模板族配对重采样。

同一 run 可支撑多张图，不增加样本量。所有扫描是一维，不运行 N×u×D×H×epsilon 的笛卡尔积。正式测试前指定主要比较与最小有意义效应，用 pilot 配对方差评估精度/功效；不追加样本直到显著。

## 7. 图表清单

每个统计图只有一个 X-factor 和一个 Y-factor。多个固定方法是系列，三个数据集是重复面板；不在同图加入第二类指标或第二个扫描参数。标题使用 **Y varying X**。下表方法缩写：X=XGAP，T=Two-stage，L=LLM-direct，NP=noProbe，SH=shallow，G=greedy。

### Efficiency：E1–E8

| ID | 标题 / 唯一 Y | 唯一 X | 系列 | 轨道与用途 |
|---|---|---|---|---|
| E1 | End-to-end latency varying dataset | D1,D2,D3 | X,T,L | NL 主比较；W1–W4 等权后汇总，分层数字另表 |
| E2 | Backend calls varying dataset | D1,D2,D3 | X,T,L | 复用主比较，全部请求实际 calls |
| E3 | Request latency varying candidate count | N | X,T,G | Controlled；候选规模的处理成本 |
| E4 | Request latency varying unbound field count | u | X,T,G | Controlled；区分部分查询的字段数与候选数 |
| E5 | Planning time varying lookahead depth | D | X | Controlled；前瞻计算开销 |
| E6 | Request latency varying action limit | H | X,SH | Controlled；配套报告完成率，不能把早失败作为便宜 |
| E7 | Backend calls varying probe price | probe 价格比 | X,NP | Controlled；信息价格如何改变真实调用次数 |
| E8 | Clarification calls varying clarification price | clarification 价格比 | X,T | Controlled；价格变化对实际获取决策的影响 |

### Effectiveness：F1–F8

| ID | 标题 / 唯一 Y | 唯一 X | 系列 | 轨道与用途 |
|---|---|---|---|---|
| F1 | Interpretation loss varying dataset | D1,D2,D3 | X,T,L | NL；可评分返回查询的平均实际 loss，覆盖率另报 |
| F2 | Correct-answer rate varying dataset | D1,D2,D3 | X,T,L | NL；全分母严格答案质量 |
| F3 | Maximum interpretation loss varying tolerance | epsilon | X | Controlled；实际 loss 与同单位 y=epsilon 参考线；证书审计另表 |
| F4 | Answer F1 varying tolerance | epsilon | X,T | 复用 F3；检验 interpretation loss 与 result quality 并不相同 |
| F5 | Trace cost varying lookahead depth | D | X | 复用 E5；按共同权重给实际资源计价，不以算法自己的估价评分 |
| F6 | Terminal cost gap varying estimation error | eta | 固定 Q/计划集上的 selector | 独立离线小实验；见第 8 节 |
| F7 | Trace cost varying algorithm variant | X,NP,SH,G | 无第二扫描 | Controlled 默认消融；同一成本定义、case 和预算 |
| F8 | Correct-answer rate varying algorithm variant | X,NP,SH,G | 无第二扫描 | 复用 F7；检查省成本是否来自错误或失败 |

排名改变次数记录到日志与 case study，不作为独立的质量指标。

### Scalability：S1–S4（附录）

| ID | 标题 / 唯一 Y | 唯一 X | 控制与系列 |
|---|---|---|---|
| S1 | Planning time varying candidate count | N：16,64,256,1024（准入后冻结） | D1–D3 同协议；固定 D、u、图、后端和动作目标；X,T |
| S2 | Request latency varying source count | 2,4,8 个实际端点 | 同事实重新分片，固定总数据、总 CPU/RAM 和 query；X,T |
| S3 | Request latency varying graph size | 快照边数：约 0.25×,1×,4× | 固定候选/动作/端点；规模为配对生成或冻结抽样，记录实际边数；X,T,SH（SH 供 S4） |
| S4 | Peak coordinator memory varying graph size | 与 S3 相同实际边数 | 复用 S3；峰值 RSS；X,SH |

D4 可将 N/图规模扩至更大值，单独注明为合成压力测试。每个到达计算、时间或内存上限的点标明截止状态；不能仅画未截止点。固定时间上限导致平坦曲线不表示常数复杂度。多项式结论来自第四章证明，曲线只说明实际开销。

### 图外、但必须保留的证据

所有图组附带完成率、答案质量、样本数、超时/拒答/不支持原因表。保留阶段耗时、转移前后计划排序、loss 证书、metadata/probe/变换次数、传输字节和 API tokens。epsilon 扫描的耗时/澄清数由同一组运行在文字或表中报告，F4 不再重复画 calls。

## 8. 估计误差实验 F6

固定一个实际状态、一个完整 Q 和同一非空、合格的 retained plan set；不在不同 query 或不同池之间求 gap。离线确定每个计划的 reference cost，在同一正尺度下归一化。用冻结随机种子施加 `estimated = max(0, reference + noise)`，逐计划保证 `|noise| <= eta`，eta 取 0,0.05,0.1,0.2,0.5 个归一化成本单位。

记录所选计划相对同池 reference 最小值的成本差，主图用每档最大差并画同单位 `2 eta` 参考线。该检查只实例化 Appendix 的 terminal-estimation lemma；不是完整策略的 approximation ratio，不把 NP 的另一个计划池放进同一 bound。noProbe 的影响由 F7/F8 检查。

若 reference 来自已知的确定性工作模型，说明这是模型内的受控检验；若来自重复实际运行，说明测量不确定性，实测值不是数学意义的 true cost。真实估计器的 held-out 误差可另在表中报告，不能假定天然满足人为施加的误差界。所有 oracle 执行均离线，不能进入正式在线成本选择。

## 9. Case Study：C1 + T1

用 D3 一条实际跨 Neo4j/Fuseki 请求，保留其原始 query ID、NL、完整 query、快照和参考答案。首选从已冻结的 transfer aggregation / RDF annotation 模板中按 query ID 顺序取第一条包含有信息量 probe 或 metadata 的成功 trace；若没有这样的 trace，报告缺失，不编造观测，也不选最大 speedup。该选择是机制案例，不代表整体效果。

C1 是 **实际 trace 嵌入当轮局部 lookahead 的树**：状态为 OR 节点，动作作为中间节点，结果标在动作到后继状态的边上。实际发生的路径用实线；仅在真实决策记录中存在的假想分支用虚线。后续每轮重规划的树不能拼成一个预先承诺的全策略；标出轮次，并突出日志实际选择的边。合并重复状态时保留轮次和信息版本。

图的唯一故事是“观测改变执行知识，进而改变物理选择”。末端简写所选计划为 source fragments + coordinator join/aggregate，让读者看出两个后端的分工；完整 native query 放伴随材料，不在节点中塞成本表。

T1 从相同 run 自动导出：round、actual action、actual observation、候选数、所选/当前最佳候选的 rho、合格计划数、最佳计划 ID。rho 必须绑定具体 Q，不能把 rho_s 写成无参数的状态标量。Probe 不应缩小候选族；probe 只重估价格时，不写成“新计划变得合格”。资格变化、计划重排和新计划插入分别记录，表中数字全部来自日志。

## 10. 实验图制作与版面

Matplotlib 输出矢量 PDF，保留 CSV/JSONL 原始记录、聚合表和绘图脚本。按最终栏宽设计，正文相近字体，目标 9–10 pt，不低于 8 pt；线型/marker 与颜色双编码，所有方法固定样式，不按胜负改颜色。柱图从零起；对数轴明确标注；不使用双 Y 轴。

8 图的 4×2 排列只是排版候选，不是缩小字号的理由。三个数据集的扫描面板用相同 X/Y 定义；必要时拆开多页或将逐数据集展开移至补充材料，不能在没有实际渲染前承诺所有图连正文只需 4.4 页。正文的每个图表单元保留单一故事；不要为了装下矩阵把不同指标放进一个子图。

暂无数据时只建立图 ID/预定文件位置和正文锚点，不生成模拟柱高、曲线或结论性 caption。最终需核查 PDF 字号、裁切、灰度辨识及图文对应；目前仅完成文本设计检查。

## 11. 执行顺序与交付物

1. **Inventory**：核对最新实现、三个数据源的现有资产与许可、API alias、硬件、容量上限和外部方法状态。输出 `inventory.json`，不启动旧 campaign。
2. **Workload builder**：实现结构抽取、类型化参数绑定、分区映射、W1–W4、独立答案和防泄漏边界。先用现有 FinBench 小图走通，再接 D1/D2；不要求先重建所有大图。
3. **Interface gate**：每个数据集运行少量只读验证，覆盖 binding、真实 probe、metadata 资格更新、一次物理变换和最终执行。API/后端调用按另行确认的预算进行；单位测试不冒充正式速度实验。
4. **Pilot**：三个数据集同协议，估计方差、完成率、资源和模板覆盖。检查是否存在信息改变物理排序的案例，同时保留无收益场景，不按结果挑正式 query。
5. **Freeze**：版本、query manifests、映射、模板 split、样本量、重复、全部参数、指标、缓存、比较方法、超时和总 API/计算预算。缺少关键输入时只暂停对应运行，不默认填配置。
6. **Run**：先主比较，再复用基准 case 做一维扫描与消融，最后规模及离线 F6；每个 run ID 一次发布，断点续跑只运行未尝试的 cell，原失败不覆盖。
7. **Report**：原始证据 → 完整性检查 → 固定聚合 → E1–F8/S1–S4 → C1/T1 → 填入第六章。不预写“更快”“损失合规”“效果显著”。

每个 run 至少记录 `run_id, case_id, template_family_id, dataset, workload, track, code_commit, method, config_hash, snapshot_hashes, mapping_hash, random_seed, status, timing, actual_calls, selected_query, loss_certificate, output_reference_id, rounds, final_plan`。私有 gold 在独立 evaluator 侧，公开运行日志不提前泄漏它。成本模型、实际观测、假想分支分别标识。

待 coding agent 确认的事实只有：三套真实资产和映射准入、实际环境版本、Qwen API 的精确 alias/解码设置、pilot 后的正式规模与预算。它可以立即开始 inventory、模板生成及本地测试；本文件不触发付费 API、全量运行或恢复旧自动任务。

## 12. 已核验的来源

- LC-QuAD 字段与模板来源：[官方项目说明](https://sda.tech/projects/lc-quad-2/)、[作者数据仓库](https://github.com/AskNowQA/LC-QuAD2.0)。提取的是结构材料，派生 workload 不报告为官方 LC-QuAD 成绩。
- FinBench：[官方规范仓库](https://github.com/ldbc/ldbc_finbench_docs)、[查询规范 PDF](https://ldbcouncil.org/ldbc_finbench_docs/ldbc-finbench-specification.pdf)。已读在线 PDF 标为 v0.2.0-alpha；正式实验必须记录实际使用版本，不将它当稳定版默认值。
- SNB：[官方规范仓库](https://github.com/ldbc/ldbc_snb_docs)、[官方数据生成说明](https://ldbcouncil.org/post/getting-started-with-snb/)。
- IMDb：[官方数据接口](https://www.imdb.com/interfaces/)。Wikidata 映射依据：[IMDb ID 属性说明](https://www.wikidata.org/wiki/Property:P345)。
- 当前接线与实验边界：[固定提交工程记录](https://github.com/anthonyche/XGAP/blob/7461415a5674cf64f6a4da1ae6c943420a95c449/docs/report/unified_prerelease_20260921.md)。这不是本轮已执行实验的证明。
