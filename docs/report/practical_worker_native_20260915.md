# 新strong共同实验入口的真实成功门已通过

实现`919fd5c`，[范围与验收](../decisions/practical_worker_native_v1.md)。此前新strong核心
真实执行、普通记录入口和共同worker回放分别有证据；现在实际子进程、普通请求、
Neo4j/Fuseki源观测、最终答案和外层封存已在同一条请求中通过。

一个新输入边界检查首次通过（0.45s），确认绑定后的36个语义操作与预写小图定义
一致，准备阶段零网络。之后一次EXACT真实请求在原冻结8节点16关系金融小图执行：

|观测|结果|
|---|---|
|独立预写gold|4行全部一致，EM=1|
|最终物理计划|1个|
|源请求|11次，core/worker/observer一致|
|源返回行/HTTP响应体|61行/15,820 bytes|
|新模型/训练/加载/重试|全部0|
|语义验证|all_declared_slots；无未验证绑定|
|外层在线时间|1,711.462ms|
|请求准备/规划/执行|11.610/79.078/1,317.675ms；嵌套在在线时间内|
|资源采样|worker约39.2MiB，source合计约899.6MiB；均在声明预算内|

这是可信模板+可信business-ID绑定的完整开发请求，输入语义来自预写fixture，不能
计作开放NL解释准确率或新的论文题目。期待答案仅由外部评分读取；worker没有gold
参数。模型调用为0，因为这条验收的语义输入已经给定，不是模型接口不可用。

采样内存不是精确峰值，可能重复计算共享页。外层在线成本包含输入读取、worker
启动、准备、规划、执行、源观测、记录与release；服务启动和离线存储准备独立记录，
不逐题加算。单次冷会话不与前轮1,373ms核心时间作提速对照。没有运行两个候选选优。

工具会话34780正常exit0，guard子进程正常exit0；Neo4j90071、Fuseki90109均已终态，
进程组清空、observer关闭。只删除本轮可重建的私有serving副本，冻结输入和全部原始
查询/响应/失败信息保留。服务关闭时Neo4j在有界等待后使用SIGKILL，store原件不变。

[总收据](/Users/anthonyche/xgap-data/practical-worker-native-20260915-v1/receipt.json)、
[共同trial](/Users/anthonyche/xgap-data/practical-worker-native-20260915-v1/trial/receipt.json)、
[外层计时](/Users/anthonyche/xgap-data/practical-worker-native-20260915-v1/trial/timing.json)、
[完整core结果](/Users/anthonyche/xgap-data/practical-worker-native-20260915-v1/trial/worker/core/result.json)、
[独立评分](/Users/anthonyche/xgap-data/practical-worker-native-20260915-v1/score.json)、
[证据索引](../../experiments/artifacts/practical_worker_native_20260915.json)。

下一步核对新strong研究契约与旧18图协议的实际不一致，整理可讨论的模式、输入权限、
RQ/X/Y和release缺口。此门不改变已批准数据优先级/旧campaign/外部baseline，也不
自动启动大图或消融。02:00总结暂停、10:00恢复。

MaterialPassport: one new development native outer integration; no held-out
population, model tokens, baseline modification or statistical speed claim.
