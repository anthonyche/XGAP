# 新strong完整查询输入与逐题实验接线

2026-09-15，北京时间10:00恢复后。代码提交`9e8d694`。这轮补齐完整可信语义
进入strong模式的入口，发布既有FinBench的两套元数据，并通过一次真实双模式tiny
study。不是开放NL准确率评价，也没有运行新的大图查询或baseline。

## 实现变化与范围

此前intake强制至少一个hole，完整确定的语义反而不能直接进入新入口。现在新增
显式closed form：必须由调用方启用，并把模板绑定到原问题文本SHA。旧接口默认仍
要求holes。算子参数、根、顺序与bag语义保持，既不加假槽位，也不由模型建立权威。
新profile的schema routing在每个请求准备时执行并计时；离线文件只保存共享schema，
不提前注入按题选择的源，也不把该在线工作藏进一次性catalog成本。

新增publisher把已冻结的FinBench authored完整语义作为**显式方法输入**；源选择
仍用原schema规则，不读取gold source assignments。原NL/gold/reference文件不变。
这种输入测物理规划与执行，不能冒充无辅助NL解析，也不能替代部分绑定的信息策略
实验。新模式preset仅是预先冻结的开发配置，尚非最终论文默认值：

|模式|合作式规划预算|候选上限|每状态terminal上限|信息/模型|
|---|---:|---:|---:|---|
|EXACT|2000ms|256|2|已完整确定，0调用|
|PERFORMANCE|100ms|64|2|同上|

两者均允许估计物理改进，保留完整可行seed。旧PERFORMANCE开发配置的terminal=1
及关闭improvement不变，属于旧版本。允许第二个terminal才有机会消费估计改进结果；
100ms到期仍可能只得到seed。软预算可在原子步骤结束时越过阈值，不是硬实时保证。

## 真实元数据发布

既有120题分别发布native和同事实RDF的closed strong profile/request/study input。
每套仍为24 development、48 estimator training、48 evaluation；原ID、问题文本、
family、split、exposure与reference pin逐一核对，保留所有原空/非空及旧曝光。
726个生成pin校验通过。发布不读取reference内容、原方法输出或图数据，不采样新题。

|表示|题数|一次性元数据准备|catalog admission|catalog build / 模型 / 数据库 / fit|
|---|---:|---:|---:|---|
|原生Neo4j+Fuseki|120|1895ms|1|全部0|
|同事实RDF|120|1968ms|1|全部0|

120题配置共享同一组冻结依赖；离线发布只admit一次catalog。在线worker仍按其请求
生命周期admit，费用如实计量。这里不是120题执行时间。原权重没有改变，跨规模迁移
仍未经校准。每个发布进程120秒外层上限，均正常终态，无重试。

原始根目录：`/Users/anthonyche/xgap-data/resolved-strong-finbench-20260915-v1`。
[元数据审计](/Users/anthonyche/xgap-data/resolved-strong-finbench-20260915-v1/audit.json)，
SHA`37bf3f81926a883bad0bc2f8085e62ce94cf91edd3b572a2a8e44953bb1e463f`。
清单是可用输入，`formal_campaign_ready=false`仍明确保留。

## 一次真实study接线验收

复用冻结8节点16关系的源副本及已有ANCHOR-01语义，事前指定一个group、两种模式。
通过新publisher→既有freeze_study→dispatch_practical_group→common worker→真实
Neo4j/Fuseki→封存后独立评分。无需重复旧gate或加载新数据。EXACT先、PERFORMANCE后。

|方法|正确行数 / EM|最终计划 / 源请求|响应body|规划|执行|完整common在线|
|---|---|---|---:|---:|---:|---:|
|EXACT|4 / 1|1 / 11|15820B|243.55ms|1516.09ms|2071.36ms|
|PERFORMANCE|4 / 1|1 / 11|15820B|102.93ms|206.37ms|567.71ms|

两者的完整physical plan内容hash相同。EXACT调用估计器11次，PERFORMANCE只有1次：
后者在可选改进构造到期后保留seed。规划开销的差异可观察；不能把总体时间差说成
PERFORMANCE加速倍数，因为后执行的一方受源预热影响，而且只有一个曝光题。
完整语义已给定，两者都正确，无法据此证明EXACT的信息获取准确率优势。
计时包含关系互有嵌套，不能把admission/search/execution等所有字段直接累加。

总计22次真实源请求、2个最终计划，0模型/token/fit/加载/baseline/重试。
所有owned源进程已回收，observer已停，只清理可重建serving副本，冻结源与记录保留。
[完成方法审计](/Users/anthonyche/xgap-data/resolved-strong-finbench-20260915-v1/tiny-study/completed-method-audit.json)，
SHA`e45446f52fe674e48c36bbac3c9f56a4fe69af55d481a840987bb5df4f9c512b`。

一次性gate脚本在两个方法及其score/journal均已封存后，误从receipt读取`timing`
字段而非单独的timing.json，汇总阶段报KeyError。原失败receipt保持不动：
SHA`af0e1a65de769a68c4d704fad22558d39c0b375b02fdd7f5fad8bf55e6c9d466`。
后续只读取并校验已保存的receipt/score/timing/core，形成独立completed-method audit；
没有重跑方法、source、模型或评分。不能把汇总错误记成查询失败，也不覆盖该错误。

## 定向验证与下一步

7项新检查+3项受影响检查最终通过。首轮7通过、3失败(0.63s)：1项发布器把带bytes
的pin传入严格profile字段，2项测试绕过TemplateInterpretationProvider，误把intake
ownership元数据直接送编译器。修正各自边界后只重跑3个失败检查(0.40s)。新增在线
source routing后，1项相关publication检查+2项原partial-mode检查通过(0.46s)；追加
实际preflight接线断言后仅该1项通过(0.32s)。不把这些重复检查累计成更多样本。
两个in-process小图模式独立返回正确14个边对计数，各1最终计划/1源请求。100/5估计
分数是有限测试fixture，不是训练精度或速度证据。没有全套回归或新消融。

下一步接齐部分绑定的同权限外部组合前端、明确实际信息动作费用/优先级，冻结最终
paper profiles与统一release protocol，再沿批准的数据次序评价。现有完整语义输入
可进入物理对照准备；不能用本tiny pair、旧NL44个结果或旧固定语义分母替代新评价。
不因为本次结果相同而强迫改估计器得分，也不重复这次成功gate。

MaterialPassport: authorized implementation and metadata publication plus one
predeclared native development integration group; no paper-level superiority,
general NL correctness, calibrated-estimator or global optimality claim.
