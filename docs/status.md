# XGAP Current Status

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
