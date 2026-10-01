# 新strong方法接入共同实验worker

实现`9bd7d15`，[接口与计量契约](../decisions/practical_worker_v1.md)。
新增xgap-strong-exact/xgap-strong-performance，使用trusted_template输入范围；它们
经已有worker命令调用普通practical记录入口，接上共同进程预算、资源监测、源观察、
封存及失败清理。保留旧one-shot方法、外部baseline、已冻结campaign方法列表与分母。

这补上了实现集成缺口。新路径经本地与回放验证；真实成功请求通过这个组合外层的
证据仍待部署门，不能把旧core native门或offline replay当成已完成的真实共同trial。

6项新检查+1项受影响检查首次通过（1.07s）：完整旧响应经新worker传递；已复现的
失败仍是失败而非空答案；common live入口拒绝offline replay并清理phase；强制独立
输入track；缺失模型usage保留unknown；实际guarded CLI进程在未知binding处拒绝、
0调用；旧外部fixed入口的source-pinned查询拒绝规则保持。

另一次持久化回放使用新worker分派：1个最终计划、两份旧native响应、一个旧模型
观察，答案仍为Cara/e4。新模型/源网络/输入输出tokens均0；历史372token不重新计费。
semantic_validation=authorized_prediction，predicate槽位明确标记未验证；discrepancy
仍为metric_deferred/null，未宣称开放NL正确性或全局最优。各模块时间/完整core结果
都有指针；缺少的共同阶段划分不造数值，也不改变baseline的native行为。

[回放验证](/Users/anthonyche/xgap-data/practical-worker-replay-20260915-v1/verification.json)、
[worker receipt](/Users/anthonyche/xgap-data/practical-worker-replay-20260915-v1/receipt.json)、
[完整core结果](/Users/anthonyche/xgap-data/practical-worker-replay-20260915-v1/core/result.json)、
[证据索引](../../experiments/artifacts/practical_worker_20260915.json)。

本轮没有启动数据库、模型或baseline，无新真实实验分数。实际guarded测试进程正常
结束；没有活动native资源。import改为只在新方法分支加载，旧baseline不额外初始化
新strong依赖。总体实验计划未因此自动变更。

下一门来自规划代码审计：预算只在外层检查，而可选物理候选域一次构造可能较大。
增加候选构造/打分之间的合作式预算检查，及时停止可选改进并保留已找到的可行计划。
仍说明原子编译不能硬实时抢占；用受控时钟/计数和小图验证，不启动新native实验。
02:00总结暂停、10:00恢复不变。

MaterialPassport: development handoff/replay; old native/model captures preserved;
no new paid results, formal campaign activation, baseline tuning or statistical claim.
