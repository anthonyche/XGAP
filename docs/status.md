# XGAP Current Status

2026-09-21 迁移方案补充：已用两个确定性小反例确认忽略后续验证／完成预算会造成饥饿。
[新增保护契约](decisions/unified_lookahead_migration_20260921.md#21-required-refinement-prevent-validation-starvation)
要求完成成本叶评分、保底完成路径及资源预留、无进展探测去重；仅改文档，尚未实现或重跑实验。

2026-09-21 新稿对齐：已读四份修订章节并完成[统一 lookahead 迁移分析](decisions/unified_lookahead_migration_20260921.md)。
研究目标改为一个系统，Lambda/epsilon 是契约参数；当前运行代码仍是下述旧版本，
新控制器、强制验证状态、metadata/probe 与逐步物理动作尚待整合。未恢复正式实验。

**2026-09-21：本轮里程碑完成，按用户要求收尾后暂停，等待讨论。**
[FinBench 正式主比较](report/chapter7_finbench_primary_20260921.md)：48 题 × 两模式，96 次全部
回答正确，服务已关闭；四个 FinBench 原生图面板及逐题 CSV 已产出。Performance 平均略快，
配对区间跨零，澄清／模型／bytes 均无节省；全 ID／活跃框分别 17/24 和 20/24 空参考。
原版 ARUQULA/FedUP 串接代码及定向测试已补，新的真实组合验收未执行。
整体三数据集／E1–E20 未完成；下文旧 ACTIVE／恢复安排不覆盖这次暂停指令。

2026-09-21 正式主比较已制定[双框冻结协议](decisions/chapter7_finbench_primary_freeze_20260921.md)：每框24题、共96个NL执行单元，ε=1/2、每配置一次，2小时/2GiB上限，结果前封存。
[原版外部依赖/Redis/lookup已通过接口门](report/chapter7_baseline_setup_20260921.md)，真实图/模型/FedUP串接待做；不改变baseline算法。

2026-09-21 最新：三结构 SF0.1 pilot 48/48 执行完成；Exact 24/24 正确，Performance 23/24。受控组澄清 1→0，但处理 11.19→12.14 s；NL 两模式均需一次模型/澄清。21/24 空参考，不能夸大高正确率；[完整结果和哈希](report/chapter7_three_shape_pilot_20260921.md)。用户已批准[双取样框分别报告](decisions/chapter7_sampling_strata_20260921.md)，实现通过 8 项定向检查，尚未执行正式双框样本。ARUQULA 原依赖/导入通过，真实组合仍待接通。Goal ACTIVE，三数据集/E1–E20 未完成。

2026-09-21 10:00 用户明确恢复，应用 Goal 为 ACTIVE。前一轮代码/报告已本地提交至
`7a764a1`，恢复后继续新增结构的真实接入、正式冻结及其他数据/方法；全矩阵仍未完成。

本轮收尾，按用户要求暂停至 **2026-09-21 10:00（北京时间）**。
[中文进展总结](report/chapter7_milestone_20260920_evening.md)：4 次真实验证答案不变，
调用 11→9、响应约 77.2→36.1 MiB；两模式共同受益，不是 Performance 优势证据。
新增三种有界结构及独立 CSV 参考，27 项定向测试通过；正式新工作负载尚未冻结。
下文 ACTIVE 和“当前下一步”为此前阶段记录；整体 Goal 未完成。

2026-09-20 T7：应用Goal ACTIVE，72小时目标已开始执行。新真实Qwen/native门已通过；
FinBench SF0.1的24题/48次pilot已全部封存，47次正确回答、1次模型超时，未重试。
主要发现是23/24空参考、受控Performance减少澄清但执行成本占主导。
见[实测报告](report/chapter7_pilot_20260920.md)。下文T6待办记录是此前时点；
正式三数据集矩阵、外部方法与可扩展性尚未完成。

2026-09-20 T6：用户的三数据集/E1–E20实验计划已采纳并开始执行。
已接好共同初始状态、执行反馈开关、完整policy和独立query-loss评分。
真实Neo4j+Fuseki的4个tiny受控配置通过；2次真实Qwen预检发现表示等价问题，
已修复并用保存输出完成零新增模型调用的RDF回放。失败记录保留。
详见[当前验收报告](report/chapter7_readiness_20260920.md)与
[能力表](../experiments/protocols/chapter7_capabilities_20260920.csv)。
这些是接口验收，尚非24例/数据集pilot、正式比较结果或20张论文图。

T4 bounded joint system implementation is complete within its declared profile
(2026-09-17): [acceptance report](report/bounded_joint_system_20260917.md),
[Chapter 6 implementation map](implementation_chapter6.md).

2026-09-20 T5补齐新版worker的批量接口，已经过统一子进程入口、压缩答案评分、
预算非回答与不重复续跑验收；见[报告](report/bounded_joint_batch_20260920.md)。
用户可同步设计第七章；正式评价配置尚未冻结，本轮没有启动全量实验。

|Item|Verified state|
|---|---|
|Current entry and legacy isolation|`xgap.api.answer`; three historical controllers moved, compatibility retained|
|NL candidates and authority|Bounded Cartesian/Top-K support, paid containment confirmation, scoped/full simulated user|
|Joint information/execution objective|Shared finite strong search, frozen estimates/fallback, feasible seed, one execution|
|Storage/memory|Streaming gzip, logical/stored hashes, raw replay support, budget-cause preservation|
|Correctness|88 targeted tests; real eight-node Neo4j+Fuseki gate; services closed|
|Current batch boundary|40 unique targeted tests; native 3-case batch: 2 answers + 1 declared budget non-answer; resume skips all attempted cells|
|GitHub|Published on `codex/m13e4-grailqa-semantic-paper-protocol`; [review PR #1](https://github.com/anthonyche/XGAP/pull/1), not merged into main|
|Chapter 7 readiness|53 distinct focused tests across T6 contracts and representation boundary; native controlled gate passed; full policy rendered|
|Formal evaluation/Chapter 7|T7 repaired live-model gate and FinBench 24-case pilot complete; formal freeze, other data mapping and external setup pending|

This does not mean universal NL support or proven overall superiority. Current
bounds and two stale historical full-model replay tests are explicit in the report.
The real tiny gate returned four exact rows versus one ε-certified Performance row;
backend call counts were equal. Storage benefits are separately measured, not
presented as query speedup. T3 remains 47 sealed/65 unrun with its original version.

[Previous status](status_history_20260917_t3.md) is historical evidence only.
