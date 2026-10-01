# Partial strong FinBench first evaluation release

2026-09-15，沿用户已批准 FinBench native → 同事实 RDF FedUP/FedX 的主评价顺序。

RQ：在相同可信部分模板、信息权限及冻结事实下，信息选择与有界物理规划的成本和
正确完成率如何？X 为方法/模式，Y 为全体题目的正确完成率、在线时间、首次可行策略
时间、额外规划时间、信息/模型/源调用及 bytes。此轮不是消融或规模 sweep。

发布采用 `partial_strong_campaign_20260915_v1.json`，不再调整已验证的
`partial_strong_cost_informed_v1.json` 参数：EXACT 2,000ms 合作式规划预算并允许物理
改进；PERFORMANCE 500ms 且不做可选物理改进。双方共享动作、候选及权威渠道，
PERFORMANCE 的关系槽可使用未验证预测。费用来自三个 development 问题的实测中位数，
不是评价结果；估计器、catalog、统计与原 24/48/48 划分保持冻结。

范围是三个自建 FinBench 问题家族、一个共享关系标签槽、可信查询骨架和已给定源分配，
不是官方 FinBench 全部交互查询，也不是任意开放 NL。原 48 evaluation 题全部保留，
原顺序不变；每方法每题一次。native 两模式共 96 cell，同事实 RDF 两 XGAP 模式和
四个显式固定信息 FedUP/FedX 组合共 288 cell。组内循环方法次序，在 48 组上平衡位置。
旧方法结果不继承；已曝光/空答案分层沿原资料标记，不把成功空结果当非空检索证据。

固定前端沿其原声明动作顺序，不调用 strong 物理优化器。FedUP/FedX 保留作者算法及
不支持语义，不能按题切换引擎或修补答案。若外部方法不能支持共同查询形式，报告完整
分母下失败；不据此宣称 XGAP 优化器提速。两 XGAP 模式可能都选择便宜的本地权威信息，
不人为增加其费用制造 Pareto 优势。

统一 worker 180s / 2GiB 采样 RSS 上限，源请求 20s，模型 45s / 512 输出 token、
每方法最多一次调用且预留 4096 token。合作式规划预算不是绝对物理计时上限；worker
监督单独执行。托管源与方法 JVM 使用既有 serving 配置，其资源另行计量，不能将
worker RSS 冒充全系统内存。源 observer 的各容量界限在发布规范中逐项冻结。

`run_practical_campaign.py freeze` 复用逐题 study 发布，校验全 48 题及 prepared store
数据/语义/client 对应，不读答案、不构建 catalog。`release.json` 将既有 candidate
输入和 schedule 关联为本轮可执行发布；不改写原 candidate 的标志。发布源码与 driver
均固定，运行时只换 owned observer 的端点。准备和 serving 启动作为离线/会话成本单列。

`run` 顺序调度、保留健康会话；失败后关闭本会话全部 owned 服务，接续下一未开始 cell。
不明确的旧 intent 保留、不重跑；旧会话无法证明关闭时停止。显式 `max-dispatches` 只
限制本次执行块，不改变全体分母或后续方法。每次调用有独立不可覆写记录；凭据只经
进程内环境/无回显输入传递，不进入代码、release 或记录。

唯一新增验证是三个 controller 风险检查：不重试 indeterminate intent；拒绝未关闭
会话；方法成功但源释放失败后先关闭再进入下一 cell。三个检查通过，不重跑已成功的
planner/源语义门。正式结果封存后再评分；后续三时间块的重复及尺度实验另行固定。
