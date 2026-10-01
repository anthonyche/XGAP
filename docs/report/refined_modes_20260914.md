# 两模式精度/相关性改造与真实NL小图结果

2026-09-14。上一轮关系预算组件之后，本轮完成precision证据与质量band、performance
起点绑定保护、可冻结的模式配置，并通过两次真实LLM＋Neo4j/Fuseki普通入口请求。
这仍是开发小图集成；正式规模上的两模式速度/准确性收益尚未证明。

## 实现了什么

Precision可用冻结catalog返回的规范名称证据对实体候选排序；名称证据仍是预测，
不变成身份权威。可设置最大proxy质量损失delta，在有界候选中先确定质量band，
再选预测最快的计划。模型confidence未校准，不能保证真实准确率。保留一个模型
请求、一个最终计划和原硬约束。[算法、Ptime和条件质量bound](../decisions/precision_evidence_v1.md)。

Performance可在已有强制起点绑定存在时，仅截断已经绑定的关系请求，未绑定关系
保持完整，避免全局prefix先丢掉起点相关的边。不会强制选绑定计划。这个保护有代价：
若估计器选coordinator，就不会应用关系截断；后续未绑定片段也仍完整读取。
[范围、行数bound与限制](../decisions/anchor_budget_scope_v1.md)。

外层candidate和runtime plan中的预算等价标记现已一致，均只指向该预算计划；
旧计划元数据中的完整查询等价声明已修正。旧记录仍对应旧commit，未被重写。
旧默认policy和baseline共享前端保持原行为。新配置的正式campaign路由尚未发布。

## 小图机制证据

12个新增针对性案例通过：precision7、anchor预算4、冻结发布1，另有1个受影响估计
案例通过。只重测发生改动的失败fixture/边界，没有全套回归。

- Alex指代Bob的受控解释：原artifact顺序返回Alice的e4，规范名称证据改为正确e2；
  年龄/身份硬约束和非权威属性保留。
- 质量/成本反例：无质量band选便宜的错误Alice，启用band后选Bob。质量proxy与成本
  为独立机制输入，不是实际模型准确性观测或新拟合标签。
- 起点e：全局prefix丢掉起点而空答；绑定后预算保持全部5行正确答案，源返回54→33行。
  普通估计器自行选择anchor_fanout_bind，执行一次、8源调用。
- 起点a/B2：源返回54→39行，保留3/6正确答案。该漏答保留，不更改完整gold；初始
  测试错误假设prefix必保留全部6行，已纠正测试范围。另修正fixture URI和JSON比较。

以上图请求实际执行，但Interpretation受控，零真实模型调用，不算真实NL准确率提升。

## 两次真实模型和数据库请求

冻结8节点16关系；新问题从account business ID2出发走1–3跳，时间严格递增且不重复
账户，寻找登录了被封禁medium的可达账户。独立gold为account3和account4各一条1跳
路径，均关联medium1/PHONE。运行时只收到NL和冻结schema，gold在返回后评分。

|模式|完整在线秒|源请求|响应字节|独立答案|模型调用|
|---|---:|---:|---:|---|---:|
|Precision，delta0.1|5.078|14|18,312|2/2，EM1|1|
|Performance，B2、anchor scope|3.920|14|18,312|2/2，EM1|1|

**不能把这里的耗时差称为预算提速。** 两模式都只有一个解释，都选coordinator；
performance的bounded fragment数为0，响应量相同，无截断。precision先运行，
两者数据库执行时间1361/203ms，有启动/缓存顺序混杂；没有统计重复。
两次解释本身3272/3237ms。这里只证明新配置能完成普通端到端请求，不证明两模式
具有实际Pareto优势，也不证明precision的真实NL准确率超过旧模式。

共2模型调用，4840输入/973输出token；0data load/catalog/fit/baseline/probe/retry。
控制器78726正常结束，所有数据库进程和observer终态。提交aa86c79；收据
`/Users/anthonyche/xgap-data/refined-modes-native-20260914-v1/receipt.json`，
SHA256 `21daac865526a4a6e2e8e3a273ed4ba4497b82feaa533e66649125146c61eff8`。
[精确指标与全部证据pins](../../experiments/artifacts/refined_modes_20260914.json)。

## 下一项直接影响提速的实现

只把这个新tiny请求的结构代入已冻结全量RDF统计做离线预测，未执行大图、未拟合：
两模式都选anchor_fanout_bind，估计777.969ms；performance可预算3个片段，却还有
4个关系片段完整读取。这不是实际全量延迟，也不使用旧评价答案调整权重。

当前绑定策略主要覆盖第一跳，后续完整关系读取仍可能支配代价。下一工程门应添加
一个确定性逐步传播已有绑定的候选计划，使后续读取也能先受绑定约束，再应用预算。
沿已验证的等值身份连接构造，不枚举组合；需明确DAG依赖、精确模式语义、预算模式
覆盖范围、候选数/Ptime上界，以及估计域内的条件质量bound。先以独立小图的多跳/
扇出/空起点反例验证；不是调整模型权重强迫选择，也不是继续catalog工程。

之后冻结实际论文模式参数和baseline独立前端路由，再继续批准的真实评价。
NL下一group11、全部44旧结果保留；Native fixed20/RDF fixed5不变，Goal active，无暂停。
