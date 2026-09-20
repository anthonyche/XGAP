# XGAP Current Roadmap

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
