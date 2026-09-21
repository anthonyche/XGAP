# 统一 XGAP：全量实验前工程验收

2026-09-21。本轮按用户“请一直执行到全量实验之前”执行，未启动新版正式矩阵，
未恢复历史自动任务。当前结论是：**声明范围内的统一骨架和真实接口已经接通；
新版全量实验发布仍需完成数据/方法准入和配置冻结。**

这是一份工程验收报告。没有把旧两模式结果改名为新算法结果，也没有由 tiny 成功
推断跨数据集效果或性能优势。当前入口、算法和限制见[第六章实现图](../implementation_chapter6.md)。

## 1. 完成了什么

- 统一入口 `answer_unified` 与 controlled 入口；Lambda/epsilon 配置同一 fixed-D
  控制器，实际观测后重规划。已移除当前文档中“搜索完整 H 层策略”和“两种模式卖点”的表述。
- 强制验证独立于候选唯一性和零损失；私有模拟用户按请求提供权威答复，模型不提供验证。
- 截断叶包含必需完成成本；保存紧凑完成配方并对每个结果预留步骤/资源；
  optional deadline、状态/记录/终点枚举上限不破坏受保护路径。unknown 不会无限重复。
- 有界物理计划池，种子不驱逐；每次单个源替换、读复用、预过滤或 bind 变换。
  假想分支不产生远程调用，也不试跑备选计划挑赢家。
- 冻结信息目标可以真实执行；有限结果类别更新依赖估计或可选规则先决条件，
  不缩小语义候选、不冒充用户权威。expectation 要求显式先验，默认 max。
- 新方法 ID/配置/manifest 接入批量、压缩、独立评分和不重复续跑；旧运行保持原版本。
- 指标区分规划 CPU/wall、certificate、选中本地动作、实际获取等待、最终执行、
  token/调用/bytes 与声明的工作单位。没有把预测值包装成实测时间。

主要实现提交：`e16d8d4`（动作空间/批量），`b6c4a60`（完成路径/记录上限），
`39142f8`（实际路径成本记录与原版客户端环境兼容）。其他两个提交只处理外部接入：
`a0cf203`（公开 metadata 的 literal constraint），`b7ec336`（固定 Jena 磁盘开销）。
每个真实验收包记录其当时的精确 commit，最后文档整理不会改写这些记录。

## 2. 真实小图结果

数据是已有的 8 entity 开发事实；这里的“原生”是 Neo4j 图源 + Fuseki 控制源，
“RDF”是同一批业务事实分别存于 Fuseki 的图源/控制源。它们不是两个不同业务数据集，
也不是本轮 SF0.1 全量实验。

|单元|结果|答案 EM / query loss|模型调用|物理动作|probe|最终计划执行|源 HTTP 请求|
|---|---|---|---:|---:|---:|---:|---:|
|原生 strict，模板输入|四行正确|1 / 0|0|5|0|1|9|
|原生 information，模板输入|四行正确|1 / 0|0|9|1|1|10|
|原生 sequential，模板输入|四行正确|1 / 0|0|5|0|1|9|
|原生第一条真实模型问题|scope 拒绝|未回答 / 未执行|1|—|0|0|0|
|原生 reserve-refusal|预期预算拒绝|未回答 / 未执行|0|0|0|0|0|
|原生独立完整 NL 问题|四行正确|1 / 0|1|5|0|1|9|
|同事实 RDF，模板输入|四行正确|1 / 0|0|5|0|1|9|

这里的五次成功均匹配独立四行参考，且独立 query-loss=0，无 certificate violation。
纯符号搜索的外部调用为零；information 单元确实多付出一次图计数请求。
所有 owned 服务关闭，原生批次续跑新增执行为零。保底不足的拒绝发生在数据库调用前。

**失败没有被修复后覆盖。** 最初模板用语被拿来作真实 NL 时，未明确规定金标准中的
时间窗口、递增时间要求、输出/排序等固定内容，模型还遗漏了一个条件，导致权威范围
确认拒绝。该记录保持 `success=false`，原始五单元总验收结果也保持 false。
随后单独发布更完整的 authored question，使用一次 Qwen 调用接通链路；这是另一项
开发接口门，不是同题重跑，也不能拿它替代原失败算准确率。

前一次调用用量为 2398 input / 351 output tokens；独立完整问题为 2594 / 486。
没有用 gold 修补模型输出。该结果证明特定声明范围内真实接口可运行，不证明任意 NL 可用。

## 3. 成本与容量观察

这次没有做性能比较实验。用于诊断的单次 planner wall time：strict 约 2.82 s，
information 约 8.30 s，sequential 约 0.86 s；真实模型成功单元约 2.76 s，RDF 约 2.56 s。
这是不同开发配置的单次观察，不能做显著性/提速结论；至少不能声称联合规划天然更快。
信息案例使用了显式的合成类别概率与成本参数，用于验证接线，不是拟合后的生产估计器。

对应计划注册表约为 3.65–7.99 MB（84–190 个有界候选计划，按序列化大小计量），
不是进程 heap 峰值。种子和 optional 计划按共同上限入库，估计/certificate 缓存有界，
decision records 也受限。中间关系释放和 gzip 证据保留继续使用已验收实现。
后端仍物化结果对象，不能称为任意规模内存安全或全流式执行。

## 4. 外部基线：忠实接入，未强行做出成功

原版 ARUQULA commit `9a3982baca03d62f7250572e300b1e4ba47727cc`，原版 lookup
commit `939b3f36fefafca444cc6dff6c568c5b559f58e0`，FedUP/summary JAR 固定哈希。
作者算法、提示、解码和结果后处理均未改。

本轮保留四个独立 attempt：

1. v1：metadata 发布器误把 literal constraint 当作 RDF resource，服务/模型调用为零。
2. v2：三份固定 Jena TDB 文件已约 604 MB，超过 512 MiB package 预算，方法未运行；
   据实际固定开销将新 attempt 的声明预算调整为 1 GiB，保留旧失败。
3. v3：原版 ChainLite 与现装 LangChain/LiteLLM 的 key 传递接口不匹配，网络调用为零；
   仅补充进程内标准环境变量映射，不写 key 到文件。
4. v4：调用链进入真实模型请求，5 次请求均在 70 s 上游边界超时；作者原有重试行为
   未修改。300 s worker 预算终止本次 attempt，源数据库/lookup/FedUP 查询仍为零，
   tokens 未知，不能记为零。wrapper 不自动重试。

v4 的状态是 `deadline_exceeded`，`composition_admitted=false`，并非答案错误或
证明作者算法差。收尾的无凭据网络诊断发现：直连 TCP 超时，而系统代理路径立即收到 401；
正常 XGAP 客户端采用系统代理，observer 原来强制直连。因此这五次超时不能归因于
作者方法或模型推理速度。已补充显式 HTTP 代理路由并以本地传输测试验证请求正文/
Authorization 不变且凭据不落盘；下一项独立 tiny 验收将使用同一网络路径。所有本地 owned 组和 observer 均已关闭；关闭客户端
不能证明远端模型计算已经停止。不能将这项未完成的组合放入一张成功查询耗时图。

## 5. 测试与仍然存在的边界

本轮按变更分组完成 75 个不重复定向测试，收尾只核对 collected IDs，不重跑整库。
覆盖 unified contract/controller/family/actions/batch 41 项、共享 bounded-joint
前端/批量 27 项、公开 metadata 3 项、原版 worker 2 项和 observer 传输 2 项。
单个物理变换用便携 RDF 实际执行并对照独立答案；真实数据库接口门另列于上表。

已保护：两个验证饥饿反例、精确步骤预算、概率零坏分支、unknown 去重、
明确资源不足拒绝、可选上限回退、种子不丢失、信息不授权语义、披露限制、
controlled 初始权威、实际选中 probe、版本匹配和失败续跑。

未宣称完成：

- 通用必需 source capability 发现/bootstrap、任意 inference rule。
- 任意 NL、跨候选无关拓扑、全部 join order、无限深路径。
- finite bytes/peak-memory 的完成证明；未知值拒绝此类有限硬保证，运行保护可能产生非回答。
- 对后端故障、bind overflow、变更快照仍能完成的保证。
- 全请求硬预算证明：当前 reservation 作用于初始化后的 online phase，初始模型/scope/
  seed 成本在外层单列，不冒充已纳入 online reserve。
- 新版三数据集全部映射、真实分片、所有外部方法接入或任何全局最优/整体近似比。

## 6. 证据索引与停止点

[机器可读索引](../../experiments/protocols/unified_readiness_20260921.json)明确记录
`formal_release_ready=false`，不是将不完整 gate 包装为全部就绪。
下列根目录均在 `/Users/anthonyche/xgap-data/`：

|包|receipt 相对位置|SHA-256|
|---|---|---|
|unified-readiness-native-20260921-v1|receipt.json|`2d326887c8d709dbd31d28e11e108711e0451be0932f94c50a96e2ebf3b06892`|
|unified-model-native-20260921-v1|receipt.json|`d3a7352103b5cbd6beefbb4d8235da7c76ea895c5c26cc941b1c4b2cf92110b2`|
|unified-rdf-admission-20260921-v3|batch/invocations/0001/receipt.json|`a451bc85fe2c1392032b58adec517a2049527f45d2bd562bfdc5d42f7ecd4ba4`|
|unified-external-admission-20260921-v4|receipt.json|`50b051e3fe435042a0b8c9e84b778d2821a3dc78fa51ff003d5fec00a20843f6`|

RDF v1/v2 在 intake 阶段分别发现 deployment 身份不同、旧 prepared receipt 缺少
input-seal 关联；保留失败并为新 attempt 校验关联，没有重建业务数据或改写旧快照。
原生与 RDF 的共同 authored fact manifest SHA-256 是
`5f289b39d057bc704274d496c2262e655946b9af763617934c97ef2eabe0677b`；
部署 ID 分别保留，不能声称整份 source snapshot 字节完全相同。
外部 v1/v2/v3 的失败 receipt 同样留在对应目录。所有成功/失败的输入、调用和结果仍可追溯。

当前停止在新版正式发布前。后续按[发布清单](../decisions/unified_experiment_release_checklist_20260921.md)
冻结第七章新矩阵/数据/预算并补齐未准入边界，再启动正式运行。
[旧 FinBench 48题/96次结果](chapter7_finbench_primary_20260921.md)保持原算法标签；
新版效果只能由下一份新发布回答。
