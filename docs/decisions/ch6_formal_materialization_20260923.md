# 正式输入物化与冻结边界（2026-09-23）

用户当前授权：完成 D1/D2 物化、三域独立测试题、实际因子输入、F6 等价计划池、
支持合同及总预算，停在全量执行之前；完成后先看一个数据集的有界结果。
现有交互式 allocation 3856566 保留，不取消、不替换。所有新准备作业使用 CPU，
模型仍使用现有外部 API。当前离线准备不调用模型。

## 数据与语义

- D1：LDBC 官方 SNB Interactive v1 SF0.1 CsvBasic/LongDateFormatter，完整
  Person/knows 核心投影；不是仓库的 tiny example。保留存储方向，不偷偷添加反向边。
  已封存 1,528 个 Person、14,073 条原始 knows 边。
- D2：官方稳定 MovieLens 20M，完整 ratings 与电影/用户核心；不再使用
  latest-small 充当正式数据。不声称有 Wikidata、TMDB 或 IMDb 联合事实。
- D3：已验证 FinBench v0.1.0 SF0.1 的 Account/AccountTransferAccount 核心。
  新 authored core cohort 与旧的 person/company 金融模板分开，不冒称官方完整查询套件。
- 每个原始边有独立 row identity，时间转换为整数毫秒；EARLY/LATE 是按完整源数据
  时间中位点划分的真实逻辑子集。它们是视图关系，物理物化边数不得冒充原始边数。
- SQLite 只作离线事实索引与独立 reference，不作被评价的图执行器。
  Neo4j 与 RDF 由相同索引流式生成，模型、查询答案和方法耗时不参与选取事实。

## 规模与源数

基础 1× 是完整声明核心。0.25× 保留原始边序号可被四整除的边及全部节点，
实际节点/边/字节数分别报告，不能声称所有尺寸精确同比缩放。4× 为四份断开连接、
身份显式改名的完整副本；明确标记 synthetic replication，不声称新增独立现实数据。

2/4/8 个源固定同一事实集：一个 control 源，其余图源按边序号确定性分片；
节点类型/身份和普通属性 stub 可重复，逻辑集合 hash 保持一致。
当前 compact lowering 的 edge/property reads 会合并所有匹配源；旧的
`schema_source_routing.source_assignments` 不能作为该入口缺乏 union 的证据。
实际 2/4/8 源的编译、执行、去重与 reference 不变性仍须单独验收后才可发布 S2。

## 冻结顺序

1. 源 archive、同事实 index、装载文件、schema、运行环境、估计器身份。
2. 明确 authored 模板族，结构归一化后隔离 development/pilot/test；常量替换不算新族。
3. 不看答案，按 uniform/active-anchor 两个独立 frame 预选题目及 private intent。
4. 离线独立 reference，有限候选合法性、真实源覆盖、部署支持、实际因子值逐份准入。
5. F6 先冻结同完整 Q 的等价物理池、同单位测量与 estimator-error 输入；不反馈到
   在线当前题规划。TS 无同 Q 同池输出时为 null。
6. 冻结 repetitions、方法顺序、缓存条件及 API/token/墙钟/存储硬上限。
7. 审计通过后才发布可执行 manifest；全量 dispatch 仍不启动。单数据集试跑单独封存。

## 当前证据

SNB 来源：[官方数据表](https://ldbcouncil.org/benchmarks/snb/datasets/)。源作业
3856702 COMPLETED，archive SHA-256
`5c476e25e9074f5b37cfe569f718aa43bef0187747b2c3bb2f02d5714c96820b`。
MovieLens 官方 archive SHA-256
`96f243c338a8665f6bcc89c53edf6ee39162a846940de6b7c8c48aeada765ff3`，
发布方 MD5 `cd245b17a1ae2cc31bb14903e1204af3` 已匹配。

流式物化作业 3856726 运行独立 checkout 3491839，D1 已完成；D2 仍在处理。
D3 首次 index 因原始时间存在无小数部分而失败，失败目录保留。已增加整秒/毫秒
解析与离线 failure replay 测试；修复后以独立新目录准备，不覆盖原记录。
以上都不等于数据库装载验收或正式实验结果。
