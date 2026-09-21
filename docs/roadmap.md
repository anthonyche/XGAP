# XGAP Current Roadmap

2026-09-21 新目标优先：按[统一 lookahead 迁移契约](decisions/unified_lookahead_migration_20260921.md)
依次整合状态／验证、固定深度在线控制器、逐步物理动作与信息工具、tiny vertical slice、
新版批量与论文接口。该顺序取代下文继续寻找双模式优势的开发目标；正式实验保持暂停，
旧结果保持冻结。新稿分析完成不等于新算法已实现或取得新版成绩。

**2026-09-21：正式主比较收尾后暂停，先与用户讨论结果；没有新的定时恢复。**
[本轮 96 次执行与四图](report/chapter7_finbench_primary_20260921.md)已封存，不能将点估计
差异宣称为 Performance 优势。恢复后仍按完整三数据集／E1–E20 计划推进，优先讨论既定
受控扫描中的澄清动作／信息成本假设、空答案对质量证据的限制；原版组合真实门、
Freebase/FedShop 映射、真实分片与其余图均为待办。本批保持冻结，不按结果替换题目或重跑。
下文历史执行顺序和 ACTIVE 状态只供溯源。

2026-09-21 正式主比较已制定[双框冻结协议](decisions/chapter7_finbench_primary_freeze_20260921.md)：每框24题、共96个NL执行单元，ε=1/2、每配置一次，2小时/2GiB上限，结果前封存。
[原版外部依赖/Redis/lookup已通过接口门](report/chapter7_baseline_setup_20260921.md)，真实图/模型/FedUP串接待做；不改变baseline算法。

2026-09-21 当前顺序：三结构 pilot 已封存 → [双框正式取样](decisions/chapter7_sampling_strata_20260921.md)及样本/资源冻结 → 原版 ARUQULA/lookup/FedUP 接入 → 已就绪数据集正式矩阵，同时完成 Freebase/FedShop 数据映射及真实分片。每个测量批次期间不并行安装依赖或准备数据。保留 pilot 的一例 Performance 答案差异和未提速事实，不通过换题或调 baseline 制造优势。Goal ACTIVE，旧暂停安排已失效。

2026-09-21 10:00 用户已恢复本任务，Goal 继续 ACTIVE。先完成新增三种结构的真实
边界验收、发布有结构覆盖的冻结工作负载，再推进正式方法/epsilon 比较及外部方法。
下述“暂停至10:00”已到期，不需要再次等待授权。

最新：本轮完成，按用户要求暂停至 **2026-09-21 10:00（北京时间）**，
见[中文收尾报告](report/chapter7_milestone_20260920_evening.md)。读取复用已通过 4 个
原生执行单元；三种新结构的候选/CSV 参考仅离线通过。恢复后继续真实接入与正式冻结，
不重跑旧 pilot，不把离线候选当作独立正式题目。下文 ACTIVE 为启动时记录。

当前执行T7：[72小时交付安排](decisions/chapter7_72h_execution_20260920.md)，应用Goal ACTIVE。
新模型/native验收和FinBench 24题/48次pilot已完成；见[结果](report/chapter7_pilot_20260920.md)。
当前优先补workload结构覆盖、核查大响应/宽扫描、原版baseline依赖与Freebase/FedShop接入；
按pilot证据冻结正式配置，不把几乎全空答案的高正确率当作质量优势。

T6接口和首轮tiny验收已完成，见[2026-09-20报告](report/chapter7_readiness_20260920.md)。
当前下一步：FinBench新family隔离的24例开发集；Freebase/FedShop的冻结数据映射和参考；
ARUQULA依赖、lookup和FedUP实际执行接线；逐集pilot后冻结正式样本、重复与资源预算。
E19/E20需要真正分片而非副本；本地磁盘保留6 GiB底线，数据部署串行准备。

2026-09-20当前优先级已进入T6：[用户实验计划](research_experiment_plan_20260920.md)
已获批准，[执行契约](decisions/chapter7_execution_v1.md)先补共同初始状态、成本反馈开关、
完整policy导出和独立query-loss评分，然后按三数据集能力门发布pilot；正式样本与总预算
在pilot后冻结，不因结果不利改题或调baseline。下文记录T4/T5来源，不是继续等待许可。

[T4工程契约](decisions/bounded_joint_system_v1.md)的1–4项已实现并通过定向验收；
第5项已发布为[审核PR #1](https://github.com/anthonyche/XGAP/pull/1)。2026-09-20用户授权补齐
[T5批量接口](decisions/bounded_joint_batch_v1.md)，与第6项写作设计并行；正式评价仍需冻结实验计划。顺序如下：

T5接口已通过[2026-09-20验收](report/bounded_joint_batch_20260920.md)。
下一步是冻结第七章工作负载、方法和资源协议，再做实际LLM小批预检并启动正式评价。

1. 收敛当前文档/入口，隔离legacy并保留replay。
2. 无损记录压缩、预算原因保真与资源小图门。
3. 有界候选构造、独立权威范围确认、按需澄清。
4. 统一成本规划、物理策略复用、一次最终执行。
5. 验收/推送GitHub，给出第六章实现证据。
6. 与用户讨论第七章实验计划后再冻结评价，不自动恢复T3或新增campaign。

[此前路线原文](roadmap_history_20260917_t3.md)仅供溯源。总体Goal尚未完成。
