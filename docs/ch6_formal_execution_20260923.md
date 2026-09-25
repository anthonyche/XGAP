# Chapter 6 正式执行与绘图合同（2026-09-23）

2026-09-25 发布归档验收更新：108 单元/390 图位置已完成原始核验。现有范围的 D1 首轮为 56 题、256 方法请求，交接次序为 native/r0 → RDF/r0；各单元内原顺序不变。全局预算、token 计量/停止合同及启动审计仍待完成，未启动实验；下述原始研究规模及 benchmark 来源缺口没有因发布成功而消失。见[验收与启动边界](report/ch6_publication_completion_39abb95.md)。

2026-09-25 readiness 澄清：当前发布恢复只覆盖 D1 56、D2 56、D3 64，共 176 道自建基础题及既有因子输入。服务器已报告生成 108 单元/390 图位置，原始归档验收与全局预算尚待完成。原计划每域每 W 层 200 道（共 2,400 道）仍是未完成的初始目标；当前 2,400 次总体方法请求不是相同计数单位。benchmark 模板来源接线和独立最终测试集仍有缺口，不能默认以当前小规模范围替代原定完整研究。见[完成回执及边界](report/ch6_publication_completion_39abb95.md)。下文图数、方法与参数合同保持不变。

覆盖 9 月 22 日计划中的旧方法清单、扫描水平和分图省略规则；旧原文/运行保留。
本轮准备至全量启动边界，不启动全量。机器合同：`src/xgap/experiments/ch6_formal_protocol.py`。

2026-09-25 补充：[真实输入的 21 图测量配方与固定参考复用](report/ch6_figure_recipes_20260925.md)
已落盘：176 道总体题、40 个因子输入，三轮去重后 4,356 个待运行方法请求。
源数/规模上的 TS 使用对应快照的原始 NL；无 planner 时间或不可评分成本保留 null。
E7 目前 probe 轴未激活，明确标记并复用固定参考。发布审计与全局预算仍待完成。

## 五方法与缺失值

固定顺序/图例 **XGAP、NP、SH、GR、TS**，每张图保留全部方法位置。

|缩写|方法 ID|定义|
|---|---|---|
|XGAP|xgap-unified-lookahead|fixed-D，逐动作获取、规划和执行|
|NP|xgap-unified-no-probe|仅禁用统计 probe|
|SH|xgap-unified-shallow|固定 D=1|
|GR|xgap-unified-myopic|即时动作成本，资格/完成保护不变；固定 D=1|
|TS|aruqula-fedx|真实原版 ARUQULA→FedX，已披露兼容配置|

无 LD；内部 `xgap-unified-two-stage` 仅留历史。TS 保留探索、后处理、错误答案；
不以 XGAP frontend→FedX 替代。参数不适用时引用固定配置的同一实测记录，不增加样本。
不支持部署标 `unsupported_deployment`，不能提取指标标 `unscorable_metric`，未跑标 pending。
数值缺失为 null，不补零、不插值假造曲线；真实观测为零才填 0。

## 绘图计划修正

1. **按用户最新决定，使用混合 workload，撤销 native/RDF 默认双面板提议。**
   题目混合单源、同构 RDF 跨源和异构跨源，比例在正式运行前冻结。
   每方法只在事前声明支持的子集统计，同时列出总题数、支持数、支持率、完成数和可评分数。
   XGAP 保留整个已准入 workload 的结果，并另表给出每个基线支持子集上的配对结果。
   不同子集的柱值是各自条件统计，不能直接相除声称提速。
   TS 已完成两源 RDF 执行，不能写成“不支持跨源”；Neo4j+Fuseki 异构联邦未支持。
   某题的源/算子/接口能力决定支持资格，错误答案、方法超时和失败不能事后移出支持分母。
2. TS 原始 API 不接受 controlled-state。机制图可显示单独标明的固定 NL 参考面板，
   不能把其 NL 总时间伪称 controlled/planner 时间，不能计算不同计时边界的配对提速。
   不替 TS 新增候选或 oracle 接口。独立 planner 时间无法提取时明确不可评分。
3. **固定 D 时输入规模的 PTIME 不等于关于 D 的多项式。**E5 只考察前瞻开销，
   记录搜索 cutoff、状态数与回退。E3 与 S1 的不同 N 网格保持原样。
4. N=8,u=8 只能是明确枚举的相关有限族，不能称八个独立二值字段的全部组合。
   实际输入必须满足 N/u；不靠常量字段、重复候选或删除可能意图补齐。
5. F3 的 Y 是实测解释损失 d；rho、epsilon、`d <= rho <= epsilon` 审计另表。
   不用 rho 替代 d，不称答案误差界。
6. F7/F8 的 X 本身就是五方法，每方法一柱；删除旧 LD 及五乘五冗余表。
7. C1 保留五面板、实际轮数；TS 展示其原始 action sequence，不伪造 AND/OR 树或证书。

## 21 张图

所有行均呈现五方法；每图一个 X、一个 Y。机制扫描固定 D1/W3，默认 D=2,H=12,
N=8,u=3,epsilon=1/3，其余条件在单因素实验内保持不变。S1–S4 仍可放附录。

|ID|唯一 X / 水平|唯一 Y|复用与解释|
|---|---|---|---|
|E1|dataset: D1,D2,D3|NL end-to-end latency (ms)|各支持子集的完成请求；支持率、失败与同子集配对另表|
|E2|dataset: D1,D2,D3|backend calls|E1 全适用请求，含失败调用|
|E3|N: 10,50,100,500,1000|request latency (ms)|精确合法候选数|
|E4|u: 1,2,3,5,8|request latency (ms)|相关族或明确的匹配 cohort|
|E5|D: 1,2,3,5,10|planning wall time (ms)|SH/GR 固定参考；非 PTIME-in-D 证明|
|E6|H: 2,4,8,12,16|request latency (ms)|另列完成率、safe non-answer、超时|
|E7|probe price: .1,.5,1,2,5|backend calls|NP/TS 固定配置参考|
|E8|clarification price: .1,.5,1,2,5|clarification calls|TS 无该工具，观测为 0 时可填 0|
|F1|dataset: D1,D2,D3|interpretation loss|另报可评分覆盖率|
|F2|dataset: D1,D2,D3|correct-answer rate|全适用分母；保留失败/错误答案|
|F3|epsilon: 0,1/6,1/3,1/2,1|max interpretation loss|y=epsilon 参考，证书审计另表|
|F4|epsilon: 0,1/6,1/3,1/2,1|answer F1|复用 F3|
|F5|D: 1,2,3,5,10|actual trace cost|复用 E5，不用 planner 估值评分|
|F6|eta: 0,.05,.1,.2,.5|terminal cost gap|五方法成本敏感性，见下文|
|F7|XGAP,NP,SH,GR,TS|actual trace cost|复用 E1 的 D1/W3 匹配题|
|F8|XGAP,NP,SH,GR,TS|correct-answer rate|复用 F7|
|S1|N: 16,64,256,1024|planning wall time (ms)|log-log，保留资源截止点|
|S2|sources: 2,4,8|request latency (ms)|固定总事实与资源，分片前后答案一致|
|S3|graph scale: .25,1,4|request latency (ms)|实际节点/边/三元组数量入表|
|S4|graph scale: .25,1,4|peak coordinator RSS (bytes)|复用 S3，源内存另表|
|C1|actual round|action/state|实线已发生，虚线假设；五方法面板|

T1 不计入图数：method, round, action, observation, preferred query, rho, preferred plan, evidence。

## F6 五方法成本敏感性

固定完整 Q、同一部署、可比较终端成本单位。先冻结等价性、实测 c(p)、归一化常数 Z，
再按预定种子产生满足 `max_p |c_hat(p)/Z-c(p)/Z| <= eta` 的误差。
Y=`[c(p_selected)-min_retained_pool c(p)]/Z`，不是全局最优差距。Z 不随 eta/方法变化。
offline 替代计划评估不能反馈当前在线请求。

每方法保留实际选择和估计器调用证据。固定 Q/固定池使四个共享方法退化成同一选择函数时，
允许曲线重合，不能为造差异改算法。只有在同一池精确取 estimated argmin 的结果适用 2eta；
不把该界推广到整个 policy，也不从方法名称推断前提成立。

TS 没有同类 estimator 扰动接口，使用原配置参考。只有其最终查询等价于 Q、成本同单位同部署，
才画实测固定 gap；否则明确不可评分。不能把错误查询的廉价结果当优化收益，不能替 TS 新加估计器。

## 输入、统计与预算

- D1=SNB-derived，D2=MovieLens-derived（20M 为正式候选，latest-small 仅开发），
  D3=FinBench-derived SF0.1 起步；只发布脚本/版本，不伪造外部映射。
- 每域每 W 层 200 题仍是初始目标，不是已发布样本。独立 pilot、真实模板族、存储/时间预算
  决定最终 n/repetitions；必须在正式结果之前冻结。已调试的 29 小题和 6 个 SF0.1 题不算 held-out。
- development/pilot/test 按规范化模板族隔离；uniform/active-anchor 两层分别报告。
  先按源结构封存选题，再计算独立参考，不按方法胜负或答案非空筛题。
- scope 只确认覆盖；私有模拟用户通过工具披露，gold 不进入模型/估计器。所有方法同一 NL、
  公共 schema/labels 和 source snapshot；TS 不拿 XGAP 的候选或私有意图。
- 每请求新 worker；XGAP 请求内缓存；TS 新 Redis/FedX/lookup host；同数据块内源服务可复用。
  预定种子交错方法。服务/lookup 设置为 offline，单列并计入总墙钟，不混入 query latency。
  不宣称 source-cold，也不把 XGAP 热缓存对比基线冷缓存。
- 源 HTTP attempts、模型 calls/tokens、bytes、lookup/federation calls 分层记录；不把 federation
  请求与展开 source 请求双算。基线恢复成功的探索错误不直接改判管道失败。
- Trace cost 仅用共同冻结的实际资源权重；缺少正权重资源则 null。不拿自己估值作为分数。
  catalog/index/preprocessing 是一次性成本，独立报告。
- 重复先在 case 内合并，CI 按模板族 bootstrap；重复不增加独立样本。Latency 统计实际完成
  请求，包含错误答案的完成请求，显示 n 和失败率；配对比值只使用同题、同源快照/部署、
  同计时边界的共同完成记录。正确率/F1 保留支持范围内的方法失败，不补入不支持题的零分。
  study 预算/观测器截断标缺失；与预先定义的方法超时区分，不伪作方法错误。

## 启动步骤

F6 的当前可评分输入是**已经可执行的固定完整 Q、独立等价性准入的同一 retained
pool**。`score_ch6_cost_sensitivity.py` 把误差后的相对估计输入真实共享 terminal
selector，再用离线实测成本评分。四个内部变体在这个子问题上共享代码，曲线预期
重合；不得为拉开曲线添加变体专属策略。TS 无可比选择记录时保留 null。该图不评价
候选解释、信息获取、计划池构造或端到端代价，也不证明整条策略的 2η bound。

|步骤|入口|产物/门槛|
|---|---|---|
|设计表|prepare_ch6_formal.py|21 图 JSON、逐格 CSV、W1–W4 矩阵、预算情景、就绪清单|
|公共 RDF/依赖|prepare_ch6_external_runtime.py|共享标签 profile、作者/JAR/模型配置 pins，无模型调用|
|离线装载|prepare_rdf_tdb.py|1–8 源，显式输出预算，6 GiB 余量，冻结后仅服务副本|
|同题五方法|release_ch6_five_method_batch.py|独立 batch schema、随机顺序、四内部配置+真正 TS|
|小规模准入|run_bounded_joint_batch.py|计量、关闭证明、独立答案评分|
|全量检查|check_ch6_formal_release.py|held-out、样本数、21 图、五方法、预算、pin、gate|
|全量启动|run_ch6_formal_campaign.py|默认 dry-run，--execute 才运行；默认最多 1 个新 cell|
|案例轨迹|export_ch6_case_trace.py|从五方法的 pinned outcome 提取实际动作；C1 JSON、T1 CSV；缺失轨迹明确标注|
|绘图|plot_ch6_formal.py|21 图、五方法、置信区间、独立取样层；C1 只读已发生动作，不画假设搜索为实线|

空设计表不算全量 ready；实际数据/held-out/factor 输入和 gate 均需存在。图表已准备、代码已接线、
实机已准入、三域全量就绪是四种状态，分别报告。

首次盘点磁盘约 12 GiB，扣除 6 GiB 余量约剩 6 GiB；不删除旧运行。现已获准直接使用 CWRU，
计算节点的存储/统一入口/现有外部 API 已通过，Linux 数据库和基线依赖另做 tiny 准入。
个人配额仍未确认；在服务器存储上运行数据服务和实验，本地保存结果索引。
软链接不能直接跨机器；远程挂载可用于文件浏览/传输，不把数据库文件经广域网挂载来计时。
仅在全部支持时的 12000 个方法请求、平均每个 15 秒就约 50 小时，
不含其他扫描；TS 每题多次模型调用，不能按“一题一次 API”估预算。

### 封存后 cohort 汇总

`aggregate_ch6_cohort.py --input-path INPUT --input-sha256 SHA --output NEW_DIR`
读取 `xgap-ch6-cohort-input-v1`：cohort/dataset、support pin、case_metadata
（case→family/question/stratum）、repetitions、trials
（case/repeat/terminal/timing/manifest pins）与共同 trace_cost_weights。
每次只汇总一个取样层。逐条核对 question、request、method、deployment 和 source version；
输出五方法支持率、缺失重复、完成数、截断数、指标与同题同计时边界的配对比值。
错误答案/方法失败保留评分；study censoring 从主数值中排除但保留计数和原始资源记录。
重复先按 case 合并，CI 按模板族 bootstrap。该脚本不替代正式 release audit。

在历史五方法 tiny 封存文件上完成零调用汇总验证：XGAP/NP/SH/GR 的已记录答案分数仍为 1，
TS 保持 censored/null，不能因旧 raw terminal 中的 0 而改判错误。
汇总产物：`/Users/anthonyche/xgap-data/ch6-cohort-aggregation-gate-20260923-v1/summary.json`，
SHA-256 `3e94ad164e6d7665c8433ab6c3cbc0ad91478b071fe32684685af242bbeef864`。
这是历史证据的汇总验收，未增加正式样本、模型调用或实验结果。

### 实际输入与图中位置的绑定

全量 release 区分 `case_bundles`（三域 overall test 分母）和 `factor_bundles`
（实际 N/u、source/scale 输入）。后者不增加 overall n；每个输入仍有唯一 case ID、
source snapshot、私有意图和独立参考。检查 controlled-state 的真实候选数/未绑定字段数，
不能只填写 N/u 标签。N/u 扫描的 TS 为不支持 controlled 接口；其固定 NL 参考须另行绑定。

`ch6_rebound_cohort.publish` 从冻结 D1 test 题包中按 ID 选取每个取样层的
window_edge/W3 子集，跨源数/规模保持同一完整 Q、候选族和私有意图；源数扫描独立
参考必须完全相同。规模扫描允许答案变化；active-anchor 资格固定在原始完整图，
不能在每个 scale 重新挑活跃题。新输入使用独立名称空间，不覆盖原 case。
源/规模变化必须引用真正物化并冻结的 prepared stores，编译通过仍需真实后端准入。

正式 release 还必须包含覆盖每个绘图位置的 `figure_bindings`：figure、method、
x_value、status，以及具体 unit/cell 引用或不可评分证据。固定参考重复引用同一组
cells，不创造新重复；F6 引用已测量、同 Q/单位的 terminal sensitivity artifact。
检查实际配置的 D/H/epsilon、controlled-state N/u、实际物化的源数/规模。价格扫描
绑定冻结的 `cost_reference`，只有指定信息价格改变；没有注册 probe 时必须标明
`inactive_factor`，不能将无变化曲线解释为信息获取策略收益。

`prepare_ch6_execution_units.py` 将已准入题包发布为有界重复的五方法 manifests，
只准备、不执行。每题的 relaxable 名称来自公开有限族中的非 hard 坐标：W1 没有
待松弛字段，W4 的 hard logical_scope 必须验证。共同 D/H/epsilon 与资源上限保留，
不能把 W3 的字段清单直接用于其他题型。TS 的调用参数继续只有公共问题和独立评分
参考的 supervisor pin，不向其传递 XGAP 配置、候选或私有用户。

总调度器按已冻结顺序预留一段请求的最坏 API/token/墙钟预算，再交给同一数据服务
会话顺序执行，默认每段至多 32 个新 cell（入口仍默认只放行 1 个）。这避免一次一题
反复复制/启动同一数据库；每题 worker、TS 服务仍独立，失败源 phase 仍强制关闭。
每段结束核对实际 usage；没有 terminal 的旧 cell 会阻止续跑，不能当作零成本跳过。
每段开始保守预留该 unit 的完整受限 package 上限与其他 unit 已保留证据之和；
不依赖未来删除来承诺存储空间。改变此分段只改变 harness，不改变方法算法或方法顺序。

同一 manifest 可显式冻结 `design.source_storage=node_local`，将所有方法共享的源服务
副本放入当前 Slurm allocation 的私有临时目录；默认历史配置仍是 evidence 目录。
永久输入、请求、答案和关闭收据继续存研究存储；磁盘 guard 合并计算两个目录。
节点本地服务副本没有成功回收时，下一次 invocation 必须先完成存储恢复，不能漏算。
服务复制边读取边校验 SHA-256，不降低身份校验；setup 时间仍与 query latency 分开。
不同存储配置的旧结果不混入同一配对比较，不把公共基础设施改善归因于某种方法。

F6 发布还要求原始测量审计：`audit_ch6_cost_measurement.py` 读取 pool 和 measurement
回执，重新核对全部重复、逐次答案与成本、median/Z/eta、实际 ready 和服务关闭证明，
不再次执行查询。`score_ch6_cost_sensitivity.py --audit-path ... --audit-sha256 ...`
绑定该证据；每个 F6 `offline_measured` 图中位置指定 `source_unit_id`，发布检查核对
其 prepared、source RSS、source observer、source storage 与 runtime 一致。未记录
运行身份的历史测量不能通过补标签获得准入；同池重测必须保留旧版并披露原因。
