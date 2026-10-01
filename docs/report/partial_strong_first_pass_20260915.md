# 新strong FinBench首轮结果与验收

2026-09-15，北京时间。本轮已结束；用户要求先验收、讨论，不再自动进入工程或实验。
自动唤醒已暂停，整体研究Goal未完成。源码冻结于`5d82b6f3bd87b1d99eb1ca45bccaa34a516b5c9c`；
本次提交只封存报告和更新说明，不合入候选优化，不改原始方法结果。

## 验收判断

**有界可信模板下的真实闭环通过；模式收益、可比较的SOTA效率优势及论文整体实验尚未通过验收。**

|验收项|结论|证据与限制|
|---|---|---|
|计划可得与真实答案|本轮通过|192次XGAP执行全部strong、1最终计划、答案与独立参考一致|
|无当前题试跑选优|本轮通过|192次均0 probe、0 fit、0自动retry；不是执行候选后选实测赢家|
|完整实验记录|通过|native 96/96、RDF 288/288均封存/评分；全部384个guard正常收尾，无indeterminate；历次journal pin不变|
|资源收尾|通过|1个native、194个RDF托管session的服务/进程/observer关闭均有记录；外层controller正常退出|
|PERFORMANCE实际优势|有限观察，未证明机制优势|native配对速度比1.015×，RDF1.101×；同模式间源调用/响应字节相同，EXACT没有选到更低估计成本|
|EXACT相对精度收益|本轮未体现|两模式全答对，均选择便宜权威信息；不代表精度模式边界未实现|
|外部SOTA效率对照|当前不足|FedUP全体在生成形式处失败；FedX全体预算截断；不能给出完成相同正确任务的速度比|
|Scalability、regret、全局Pareto|未验收|只有单一SF及本轮一次观测；未做对应尺度/独立oracle/多预算评价|

## 数据、问题与运行范围

FinBench v0.1.0 SF0.1映射为55,604个实体、309,577条关系。48道evaluation问题来自
既有三个自建家族，各16题；不是官方全部FinBench交互查询。24 development / 48 training /
48 evaluation划分保持，历史曝光不因本次换版本清零。

输入是可信有界查询骨架、一个共享关系标签槽、给定逻辑源分配；native/RDF逐题输入权限、
原请求、author semantic input、authority及参考hash对应一致。它不是任意开放NL质量测试。

|查询家族|题数|空参考|非空参考|
|---|---:|---:|---:|
|所有权与转账|16|16|0|
|带时间约束的转账路径|16|12|4|
|风险聚合与排序|16|5|11|
|合计|48|33|15|

两个表示和两模式均为15/15非空问题正确。此前checkpoint-001将非空题分布写成全部在
第三家族，是叙述错误：正确分布为0/4/11；原始逐题CSV和评分未改变。纠正记录与旧文本
均保留，不用100%总体数掩盖空答案占比较高的限制。

本轮每方法每题只运行一次，循环平衡方法位置；不是六轮重复取平均。native使用真实
Neo4j+Fuseki，same-facts RDF使用真实RDF源。固定外部方法是“Fixed info + FedUP/FedX”
组合，信息前端不是作者引擎本身的NL或strong能力。

## 完整结果

|表示/方法|正确答案|非空题正确|在线时间中位数|
|---|---:|---:|---:|
|Native · XGAP EXACT|48/48|15/15|12.832 s|
|Native · XGAP PERFORMANCE|48/48|15/15|12.623 s|
|RDF · XGAP EXACT|48/48|15/15|29.319 s|
|RDF · XGAP PERFORMANCE|48/48|15/15|26.552 s|
|RDF · Fixed info + FedUP EXACT|0/48返回正确答案|无完成答案|不作为正确完成延迟比较|
|RDF · Fixed info + FedUP PERFORMANCE|0/48返回正确答案|无完成答案|不作为正确完成延迟比较|
|RDF · Fixed info + FedX EXACT|0/48返回正确答案|无完成答案|不作为正确完成延迟比较|
|RDF · Fixed info + FedX PERFORMANCE|0/48返回正确答案|无完成答案|不作为正确完成延迟比较|

FedUP两模式共96次均为原生`UnsupportedOperationException`，全部保留日志并查到
生成查询中的`extend`形式；不能扩大成“FedUP不能做所有聚合”，也不能当作planner速度收益。
FedX共96次均为harness预算截断：64次响应预算、32次调用预算；未观测到完整原生答案，
不代表已证明答案错误。调用预算允许65,536次forwarded请求；图中65,539包含被拒绝请求。
512MiB阶段响应阈值可被并发请求越过，属于停止触发阈值，不是响应总量绝不超出的硬保证。

![完整RDF结果](/Users/anthonyche/xgap-data/partial-strong-finbench-campaign-20260915-v1/full-first-pass-report/figures/rdf-outcomes.png)

上图以每方法全部48题为分母，区分返回正确、错误、预算截断与其他失败。外部失败仍应
如实出现，但当前这张图不能证明XGAP优化器胜过可完成共同任务的外部系统。

## 性能模式：观察到了什么，尚不能解释什么

配对速度比定义为每题EXACT在线时间除以PERFORMANCE在线时间，再取48题中位数。
它与“两个中位数相除”不是同一个统计量。

|量|Native|RDF|
|---|---:|---:|
|配对速度比中位数|1.014855×|1.100574×|
|配对节省时间中位数|208.745 ms|2,972.837 ms|
|PERFORMANCE较快题数|43/48|45/48|
|EXACT / PERFORMANCE搜索中位数|270.267 / 89.598 ms|114.849 / 35.461 ms|
|两模式源调用数完全相同|48/48题|48/48题|
|两模式响应字节完全相同|48/48题|48/48题|
|EXACT从首个策略改善所选估计成本|0/48题|0/48题|

Native约181.5ms的配对规划差距可以解释其大部分约208.7ms总差距。RDF规划差距只有
约80.2ms，而执行阶段配对差距约2,747.8ms。**所以不能将RDF约1.10×直接归因于
搜索算法或更优源计划。** 当前记录不能分离会话、JVM/缓存、记录与运行变动的因果贡献。
不为解释这个结果立即追加重复实验；先讨论是否存在值得单独验证的机制假设。

所有在线时间是带观测/持久化的请求到durable outcome时间，不是无监控的数据库纯延迟。
源observer收到完整响应并保存后才转发；其计时混合上游、持久化与下游成本，缺少纯上游
计时，且并发时不能直接求和。未测量的observer开销不能事后扣除。CPU/RSS仅覆盖声明的
method/source进程组，不能冒充整机或整个harness成本。

## 信息和数据读取成本

192次XGAP执行均调用一次本地关系权威、零模型，说明此输入/费用下planner选择了便宜
的验证路径；不代表模型接口不可用。四个固定外部组合合计192次模型调用，服务报告
75,992输入token、3,840输出token，共79,832。原compact usage字段遗漏已从封存的
模型调用记录恢复为独立sidecar，未改原receipt、未追加模型调用，缺失usage为0条。
对应代码修复仍是待讨论候选，尚未合入或测试。

各表示每种XGAP模式总计256次源请求。RDF每题中位工作量如下：

|家族|源请求|源响应|
|---|---:|---:|
|所有权与转账|5|59.4 MiB|
|时序转账路径|6|107.3 MiB|
|风险聚合排序|5|71.5 MiB|

![同图观测工作量](/Users/anthonyche/xgap-data/partial-strong-finbench-campaign-20260915-v1/full-first-pass-report/figures/rdf-observed-work.png)

FedUP零源请求是前置失败；FedX工作量是截断前观察。均不能解释成完成相同任务所需
的完整工作量。catalog、冻结统计/训练、准备源与summary的费用在离线账本；本轮服务
启动、压缩、归档另列，不把反复会话启动或harness维护都叫作catalog一次性成本。

## 是否有值得继续的优化计划

目前有一个**有量化依据的局部候选**，但还不足以支持立即重复整套评价：

- 一个已封存时序查询有两次仅输出字段`t2/t3`不同的完整关系读取，每次47,184,395 B；
  该题全部响应112,484,339 B。若编译器等价与字段恢复检查通过，可省去其中一次读取，
  对该题约42%响应字节；这不是已经测得的延迟改善，也不是所有题都能节省42%。
- 候选采用同冻结源、编译器验证、现有字段投影恢复；不改源查询语义、不截断行，不执行
  候选来选优。实现草稿/小图测试已准备，但本轮未合入、未运行。若讨论后值得验证，
  应先一个tiny门；它会惠及两个模式，不能独自证明精度—性能权衡。
- 估计器当前基于toy工作代理、未校准迁移，部分特征不能区分相同key数但不同扇出。
  这是后续相对排序研究的候选问题；不能靠重拟合同一批无法区分的特征或评价时间解决。
- 研究层面更大的缺口是可比较外部方法及能体现信息选择权衡的输入条件。已批准的
  bounded FedShop有静态准备，但没有启动新生成或执行。不能为了制造胜出而改变
  baseline或人为抬高澄清费用。

建议先暂停循环，讨论“这个局部优化是否值得一次小图验证”以及“下一组输入怎样
检验核心research question”。没有明确机制、预期收益和小型否证门，不继续堆消融。

## 可复核材料

原始目录：`/Users/anthonyche/xgap-data/partial-strong-finbench-campaign-20260915-v1`。

- [完整逐题CSV](/Users/anthonyche/xgap-data/partial-strong-finbench-campaign-20260915-v1/full-first-pass-report/cells.csv)
- [统计与来源hash](/Users/anthonyche/xgap-data/partial-strong-finbench-campaign-20260915-v1/full-first-pass-report/summary.json)
- [验收计数](/Users/anthonyche/xgap-data/partial-strong-finbench-campaign-20260915-v1/full-first-pass-report/acceptance_metrics.json)
- [计时诊断](/Users/anthonyche/xgap-data/partial-strong-finbench-campaign-20260915-v1/full-first-pass-report/timing-diagnostic.json)
- [关闭与FedUP日志核对](/Users/anthonyche/xgap-data/partial-strong-finbench-campaign-20260915-v1/full-first-pass-report/closure-and-failure-audit.json)
- [已报告模型usage恢复](/Users/anthonyche/xgap-data/partial-strong-finbench-campaign-20260915-v1/full-reported-model-usage.json)
- [最终controller记录](/Users/anthonyche/xgap-data/partial-strong-finbench-campaign-20260915-v1/continuation-000.json)
- [图形人工检查](/Users/anthonyche/xgap-data/partial-strong-finbench-campaign-20260915-v1/full-first-pass-report/figures/visual-qa.json)

release SHA-256 `240590475560867b1ac0a5aaf3cd029fcc9d45de2673f5d93b59a0082e2a8c60`；
summary SHA-256 `0c3c300a62368fa857ccaf84c4c35487c48c264d72f27c98d2aa3b697683e718`；
continuation SHA-256 `603cc4bd96662f8e0479905664bc7c91e6d95719c7aae09b616c75d435f1f36e`。
53个已关闭session的原source-observations已归档，文件内容及逐文件manifest/hash完整保留；
使用归档恢复工具可重建原路径，不声称这些已归档路径现在仍原地存在。

本次验收只读既有结果并生成统计/图表，没有新增实验查询、模型调用、拟合或软件回归。
