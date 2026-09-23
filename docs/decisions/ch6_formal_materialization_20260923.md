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

## 后续接线与待实机准入

终端随后再次显示 CWRU Single Sign-On，已请求重新登录。3856726 的 D2 状态为
断开前最后一次观测，不能据此宣称现在仍在运行或已完成。Slurm 作业不依赖浏览器会话；
恢复后先读取既有结果，成功的 index 复用，不重建 20M 数据、不覆盖旧失败。

`publish_ch6_heldout.py` 发布三域 authored 问题。development/pilot/test 使用不同
模板族；结构身份抹除常量、域标签和有界参数值，保留方向、连接、过滤运算符、
分组/贡献粒度及排序。更换 ID、hop 数或 top-k 不是新模板族。
test 包括窗口边、zigzag、排序分叉、矩形闭环、带 incoming witness 的有界路径、
见证去重 count/sum、排名 count；D2 的同类型路径、D1 的非平凡金额 sum 明确不适用。
这些是领域派生题，不冒称原始 SNB/FinBench query cards。

两个取样 frame 分别按 ID hash 排序选取。active-anchor 只检查是否有原始出边；
先封存完整选题/私有意图，才计算答案。空参考保留；reference timeout 是发布失败，
不能改成空表，也不能换题。每个 frame/W 层在读取答案之前按种子平衡分配 native/RDF；
两部署生成不重叠的 case ID，W1/W2 是图源，W3/W4 同时用图源与 control。
正式 n 和 repetitions 仍需在材料实际封存后发布；当前代码没有冒称 200 题已备好。

`ch6_sql_reference.py` 使用独立 SQL/递归 CTE，保留平行边、贡献粒度和路径无环语义。
4× 的快捷 reference 只允许每个连通分量都锚定原始副本；未锚定的全局聚合拒绝该捷径。
不复用 XGAP 编译器或物理计划来产生 gold。

`publish_ch6_factor_inputs.py` 创建实际 N/u controlled families，验证所有查询互异、
实际候选数和模糊坐标数。固定 N=8、u>3 时明确使用相关有限族；不称独立笛卡尔积。
D1 的单位 edge measure 恒为 1，因此用真实 edge-ID 范围坐标代替虚假的 measure 歧义。
这些范围扫描是受控机制输入，不冒充 NL benchmark；TS 保留单独的固定 NL 参考/不可评分项。
源数与 scale 仍必须由真实分片/物化快照和后端不变性检查准入。

`prepare_ch6_cost_pool.py` 从同完整 Q 生成受限的已检查 physical rewrite 池；
`run_ch6_cost_pool.py` 默认 dry-run，显式执行才会启动 CPU/数据库测量。
固定顺序、3 次重复、scheduler execution 毫秒单位，源缓存按预定次序演进，不能叫 cold-cache。
只有固定池所有试次都完成且匹配独立参考，才冻结中位成本、共同 Z 和 eta 误差表。
失败不从池删除，不选测过的最快计划反馈在线规划。方法选择尚须读取实际方法轨迹；
TS 没有同 Q 同单位证据时保持 null，不能由池的 argmin 冒充其选择。

`freeze_ch6_mixed_support.py` 要求真实 backend roundtrip、成功 stores 和当前 profile
身份一致。仅编译通过的题包不能冻结成正式支持合同；错误答案/超时不改变支持子集。

本地新增小图 gate：7 个测试通过，覆盖独立答案、路径、分层、N/u、F6 成本单位及
误差边界；另以临时小图走过完整题包/profile/4-plan pool 发布。全部零模型、零后端调用，
临时 fixture 不计正式数据/实验结果。服务器上的真实题包、成本和总预算仍待冻结。
# 2026-09-23 重连接续记录

以下记录补充本文件原决定；不改变题目、方法或正式运行授权。

- 3856726 已结束：D1 完整核心成功；D2 index 成功而旧导出批次上限失败；
  D3 旧时间解析失败。复用成功的 D1/D2 输入，保留所有失败目录。
- b66d28d 的 CPU 3856913/3856914/3856915 分别负责 D1 stores、D2 导出、D3 重建。
  D3 完整 20,409 节点/79,909 原始边成功；1 个主视图 + EARLY/LATE 分片共 159,818
  视图边，不能当作原始边数加倍。
- D1 RDF stores 装载成功（16.63 s）。Native import 因 Picocli 可变参数把末尾
  `neo4j` 当作文件失败，非数据/语义问题。修复只调整数据库参数位置，同版本本地
  2 节点/2 平行边实际导入成功，证据保存在
  `/Users/anthonyche/xgap-data/ch6-bulk-cli-replay-20260923/receipt.json`；
  服务器真实数据装载必须另行成功，不以此替代。
- `check_ch6_core_backend.py` 将整个冻结题包的目标查询逐题编译并在独立工作进程中
  执行一次，最后与 source-only SQL 参考比较；顺序固定，不挑成功题，不重试。
  这是离线数据/编译器/执行准入，拥有目标查询是该步骤的定义；不得把它混入 NL
  或 planner 结果，也不得把观测回填当前查询的估计器。
- Backend gate/F6 测量的临时 serving copy 预算显式取冻结 stores 的字节数，另加
  2 GiB 证据余量，完成后只删除可重建 serving copies。避免大数据复制被误记为
  2 GiB query evidence 超额；原始 stores、失败及执行证据保留。
