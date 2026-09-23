# Chapter 6 正式执行与绘图合同（2026-09-23）

覆盖 9 月 22 日计划中的旧方法清单、扫描水平和分图省略规则；旧原文/运行保留。
本轮准备至全量启动边界，不启动全量。机器合同：`src/xgap/experiments/ch6_formal_protocol.py`。

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

1. E1/E2/F1/F2 默认 native 与共同 RDF 两个面板；TS native 标不支持。
   五方法直接比较使用相同 RDF，不跨部署计算提速。每个面板仍是同一个 X 和 Y。
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
|E1|dataset: D1,D2,D3|NL end-to-end latency (ms)|共同完整返回集；失败/覆盖率另表|
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
- 重复先在 case 内合并，CI 按模板族配对 bootstrap；重复不增加独立样本。latency 共同完成集
  需显示 n；正确率/F1 保留所有适用请求；study 预算未执行部分标缺失，不伪作方法错误。

## 启动步骤

|步骤|入口|产物/门槛|
|---|---|---|
|设计表|prepare_ch6_formal.py|21 图 JSON、逐格 CSV、W1–W4 矩阵、预算情景、就绪清单|
|公共 RDF/依赖|prepare_ch6_external_runtime.py|共享标签 profile、作者/JAR/模型配置 pins，无模型调用|
|离线装载|prepare_rdf_tdb.py|1–8 源，显式输出预算，6 GiB 余量，冻结后仅服务副本|
|同题五方法|release_ch6_five_method_batch.py|独立 batch schema、随机顺序、四内部配置+真正 TS|
|小规模准入|run_bounded_joint_batch.py|计量、关闭证明、独立答案评分|
|全量检查|check_ch6_formal_release.py|held-out、样本数、21 图、五方法、预算、pin、gate|
|全量启动|run_ch6_formal_campaign.py|默认 dry-run，--execute 才运行；默认最多 1 个新 cell|

空设计表不算全量 ready；实际数据/held-out/factor 输入和 gate 均需存在。图表已准备、代码已接线、
实机已准入、三域全量就绪是四种状态，分别报告。

首次盘点磁盘约 12 GiB，扣除 6 GiB 余量约剩 6 GiB；不删除旧运行。大快照和 4× 材料需要
更多存储或明确的顺序物化预算。仅 12000 个 RDF 方法请求、平均每个 15 秒就约 50 小时，
不含其他扫描；TS 每题多次模型调用，不能按“一题一次 API”估预算。
