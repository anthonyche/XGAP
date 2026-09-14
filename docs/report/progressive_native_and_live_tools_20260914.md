# P-S3 真实组件门与新信息工具 live 接口证据

2026-09-14，接续 `c384c1f`。本轮先以 `555dad0` 扩展既有tiny组件脚本，随后以
`efac01c` 增加单调用live提议门。总体Goal active，未完成整体系统/论文评价。

## 真实逐跳执行

复用已冻结的8节点16关系tiny native stores，独立服务副本运行；没有构建catalog、
重新加载原始数据、训练、baseline或全量数据执行。预先声明只执行一个
`progressive_entity_bind`组件计划，冻结估计器的排序照实记录，不让当前结果反向选计划。

- 真实Neo4j+Fuseki：一个最终计划，14次源请求，4行gold全部一致。
- 8个bind节点，其中3个来自已有fanout，5个是新增的逐跳/身份连接限制。
- 收到16,252B HTTP响应体，执行1516.133ms。观察器记录原始响应，所有进程与观察器关闭。
- 冻结模型依然选择coordinator（估计28.933ms），逐跳候选估计717.281ms。
  组件门预先指定新候选以检查可执行性，**不是声称普通planner选择了它**。

随后只读取本轮及既有fanout封存记录，未重发查询。旧receipt/result哈希校验通过；
两计划的semantic equivalence key一致，只有预期5个native artifact改变，最终行相同。

|封存记录观察|旧第一跳fanout|新逐跳绑定|
|---|---:|---:|
|后三跳返回行|24|14|
|所有源返回行|62|51|
|HTTP响应体字节|17157|16252|
|源请求|14|14|
|最终答案|4行gold|同4行gold|
|各自会话执行ms|1210.506|1516.133|

两次是在不同时点的独立冷会话中运行，不是交错/平衡重复的延迟对照；不得用这两行
时间声称提速或变慢的因果结论。行数与字节下降表明实际读取限制生效，尚未证明总体
延迟优势。协议固定开销和新增依赖可能抵消小图上的传输收益，须用正式协议测量。

## Live LLM 适配器

通过用户已提供的外部服务测试`qwen3.8-27b`，使用新practical适配器与既有
OpenAI-compatible resolution provider，一次请求，无repair/retry。请求只包含极小
语义槽与两个候选ID，没有源数据或原生查询。返回`predicate:knows`，非权威；实际
311输入+19输出=330token，355.219ms，用量已报告。凭据未写入artifact/仓库。

这是候选协议组件门。`works_for`是协议中的备选ID，没有被加入或冒充冻结执行catalog。
没有通过该请求执行图查询，因此不把该证据与上面的原生组件拼成“一次live端到端”。
模型输出仍不能成为EXACT语义权威，LLM confidence不是用户尚未定义的discrepancy。

## 可复用零网络回放

新增[scripts/replay_native_component.py](../../scripts/replay_native_component.py)，使用
已封存artifact身份、动态参数与哈希索引回放原组件；每份响应只能消费一次。
14个原始请求全部匹配，最终4行答案一致，0网络/模型调用。脚本同时保留原执行是否
成功，忠实重现失败不会把原失败重标成成功；本次验证的是成功的逐跳执行回放。
这是为后续failure replay准备的现有格式入口，未宣称本轮已覆盖全部失败类别。

## 证据与接续

[本轮证据索引](../../experiments/artifacts/progressive_native_and_live_tools_20260914.json)，
[真实组件receipt](/Users/anthonyche/xgap-data/progressive-binding-native-20260914-v1/receipt.json)，
[源响应离线核对](/Users/anthonyche/xgap-data/progressive-binding-native-20260914-v1/capture-analysis.json)，
[live模型receipt](/Users/anthonyche/xgap-data/practical-model-action-20260914-v1/receipt.json)，
[零网络回放receipt](/Users/anthonyche/xgap-data/progressive-binding-native-20260914-v1/replay/receipt.json)。

当前已证明：新信息动作可实际调用外部模型，新执行候选能在真实双后端保持答案并
减少读取，新响应格式可回放。尚待：live信息动作与strong planner在同一次普通请求
内的整体门、对齐两模式的发布配置、真实成本与估计排序评价、用户discrepancy理论及
论文实验。下一步优先补这条有界整体链路；保持toy/replay，不重复旧大题、不调baseline。
