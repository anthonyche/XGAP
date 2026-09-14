# 可选规划工作按预算停下，保留完整可行方案

实现`8f01b2e`，[算法与时间边界](../decisions/cooperative_planning_budget_v1.md)。
此前strong搜索只在域回调外检查时间，一次回调可能把可选候选全部构造、打分后才返回。
现在在候选构造、逐跳组合、规范化和预测之间检查同一请求预算；到期后停止继续改进，
保留完整基础计划或已经完成打分的更好计划。第一份可行计划仍允许原子编译完成。

6项新定向检查+1项受影响完整回放首次通过（0.60s）：两模式在基础编译耗尽预算后
跳过估计，仍执行一个正确计划；构造中断不继续生成后续候选；已完成的较好估计不会
被到期覆盖；逐跳中断不发布半成品；无预算回调的旧候选域保持一致。小图实际进程内
SPARQL返回bag计数14，单次请求只有一个源调用。100/5是受控测试估计，非训练结果。

检查命令：`PYTHONPATH=src:tests:scripts /tmp/xgap-directed-tests.qU2YfW/venv/bin/python
-m pytest -q tests/test_cooperative_planning_budget.py
tests/test_practical_preparation.py::test_ordinary_record_admits_bundle_once_and_preserves_full_replay_outcome`。
原工具会话89080已确认exit0；不为生成新输出再次运行成功检查。

这使性能模式的软规划预算能作用到可选工作的内部，但不保证硬实时：单次编译、
序列化或估计调用仍可能越过截止点，返回和封存也有成本。记录明确给出
hard_real_time_bound=false；外层进程保护与这个预算分开。候选数量与输入上限仍是
Ptime依据，没有新增近似比、全局最优或discrepancy保证。

本轮0新模型、真实数据库、fit、baseline或数据加载。原子补丁首次因上下文不匹配
未应用，校正后一次测试通过；没有失败测试或付费重跑。类型注解及diff检查随后完成。
[证据索引](../../experiments/artifacts/cooperative_planning_budget_20260915.json)。

下一门是新strong worker在共同外层监督下的真实tiny成功请求。已完成的core native门
与离线回放没有验证实际子进程、源观测、答案封存、计时/资源账本的组合。只做一条
可信模板请求，沿用冻结小图，无LLM或大数据、无baseline调参；不是重测两模式优势。
02:00收尾总结，10:00恢复。

MaterialPassport: controlled development budget checks and affected saved replay;
zero new network/tokens/training; no paper performance result or hard-time claim.
