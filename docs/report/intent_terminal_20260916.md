# T1：可执行意图证书与 terminal-first 小图门

2026-09-16。用户授权“可以提供一个理论定义”，本轮给出
[完整定义、证明、复杂度与限制](../decisions/finite_intent_discrepancy_v1.md)。
此前审计和M0/M1证据保留，本次不是新大数据实验或基线比较。

## 已实现

- `intent_certificate.py`：冻结完整意图家族、固定/硬字段、加权差异和最坏情况证书；
  使用精确分数；缓存按家族、metric、快照、epsilon、观测隔离；拒绝隐藏字段差别、
  常量维度稀释、越界/矛盾回复及缺少覆盖依据的认证。
- `intent_policy.py`：同一个terminal-first循环配ExactTerminal或BoundedTerminal；
  认证后才做物理准备，否则询问一个槽并更新状态；预算最后一个回复后仍先检查terminal。
  私有模拟用户只返回被问槽，不泄漏能识别正确候选的完整query hash。
- `intent_execution.py`：接回已有compact lowering、minimum-call可行规划和协调器；
  两模式用同样的物理profile、source snapshot和候选顺序；仅一个最终执行。
  没有把未验证的Performance语义伪装成`BindingEvidence`。

这是opt-in有限家族入口；主NL worker和原AND/OR搜索器尚未改用它。新的逐槽fallback
有明确次数上界，但没有预构造所有结果的物理后续，不标记`strong_plan_verified=true`，
root gap保持null。公开候选已经给定；本次证明延迟物理计划准备，并未完成开放NL的
lazy候选生成或全部四类信息动作的统一优化。

## 可复核的机制结果

原始目录：`/Users/anthonyche/xgap-data/intent-terminal-20260916-v1/`。
保留公开家族、各模式私有oracle文件、公开观测ledger、证书、最终物理计划/源查询、
真实RDFLib执行及执行后独立评分。使用已有8节点事实，graph/control两份RDF源；
没有运行Neo4j/Fuseki服务、模型或大数据。源调用指本地SPARQL适配器调用。

公开意图空间是跳数{1,2}×起始时间{Jan1,Jan2}四个查询，两个维度等权。
隐藏用户选择2-hop/Jan2；相同初始状态不包含它的选择。泛化NL问题及家族为已知toy，
不作为新论文测试集。参考由已保存独立小图答案/时间边界案例确定，不由XGAP结果反推。

|配置|澄清预算|实际澄清|准备/最终执行|返回结果|意图距离|答案Jaccard距离|
|---|---:|---:|---:|---|---:|---:|
|Exact ε=0|2|2|1 / 1|3行，与参考一致|0|0|
|Bounded ε=1/2|1|1|1 / 1|4行，多1行|1/2|1/4|
|Exact ε=0|1|1|0 / 0|预算不足，拒答|未返回|未返回|

两次成功执行各有11次源适配器调用；没有源调用减少。均0模型调用/0token，因为
这是公开意图候选之后的确定性机制门，不是NL解释评价。沒有注入真人等待成本。

首次观测的Exact/Bounded：证书0.131/0.097ms，oracle处理0.113/0.039ms，
controller+adapter在线210.900/140.139ms；后端执行200.718/129.953ms。
这是固定顺序的单次本地观测，首次解析/进程内缓存与执行波动未受控，**不计算speedup
或声称统计显著**。总差不能归因为少问一次（被省询问本身远小于该差）。公开家族
构造在此在线计时范围外；首次距离表计算仍计入certificate_ms。

初版receipt字段`source_bytes`误用了协调器的`bytes_moved`（0），不代表测得源响应
字节为0。原记录保留；`measurement_correction.json`注明应称`coordinator_bytes_moved`，
source wire bytes未知/不适用，因为本地适配器不走HTTP。脚本输出已改正，无重跑。

## 验证与结论

11项新增定向测试覆盖：四种隐藏真值的所有合法小域前缀、上界与单调性、epsilon=0
一致、硬约束、OTHER/覆盖未知、缓存隔离、回复作用域、预算边界、准备/执行失败、
不提前规划/不执行候选，以及最后的双源编译执行门。没有全量回归或额外模型请求。

这证明在声明完整家族下，Performance能在语义差异界内少买信息，并在更小澄清预算
下返回答案；同时保留了答案真的变差的观测。它不证明收益在真实workload上普遍存在。

**动作集限制必须保留。** 本toy只允许逐槽询问；它不是最优信息策略对比。现有系统
还能够一次获取完整query intent。如果这一动作很便宜，Exact也可能一问结束。
后续必须让两模式拥有相同的full-intent/逐槽动作，计入真实成本后重新检查机会；
不为了展示2→1次而限制Exact。旧开放NL traces缺完整家族依据，仍不能补发epsilon证书。

下一步范围是把可插拔terminal接回共享NL/AND-OR信息层，明确槽域/结构覆盖证据，
考虑可分解槽域上界以免显式列举语义组合，并保留full-intent可行fallback。
大规模frontier/SOTA实验仍待这些共同边界接通后再冻结计划。
