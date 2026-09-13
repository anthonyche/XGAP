# 完整 SF0.1 的冻结 RDF 输入 — 2026-09-13

完整FinBench SF0.1已发布为新的RDF实例配置与互斥规范事实表示，覆盖55,604实体、
309,577关系。此步只做离线准备：**没有启动数据库，没有查询大数据，没有模型调用
或新评价结果。**

复用原618,038,554字节graph文件，未复制或重写。新control文件50,106,645字节，
将55,604个实体各自的type/sourceId/xgap_id移至显式本地辅助词汇，共166,812条元数据
token重写；真实属性及字面值不变。采用已通过tiny语义与真实两源验证的同一发布器。
所有RDF方法将看到相同的事实和辅助元数据，不能为单一方法额外隐藏或补充数据。

原59,587-entry catalog和原32条tiny观测训练模型继续冻结复用，没有catalog构建、
重新拟合或graph复制。发布器用网络/fit拒绝桩执行，所有外部调用为0。两个发布阶段
分别3166.405ms（实例映射）和5189.745ms（互斥元数据衍生），均为一次性成本。

发布后的包装校验首次错误比较相对catalog路径`catalog`与规范化绝对路径，触发
AssertionError；两个发布阶段此前均已成功。只修正审计比较方式，核对解析后路径和
bundle hash完全相同，不重复发布、不重建文件。该失败及未测得的整个包装总时间
保留为unknown；不能把两个阶段相加冒充完整包装总时长。

[审计与实际文件pin](../../experiments/artifacts/full_rdf_profile_20260913.json)。

- 配置：`/Users/anthonyche/xgap-data/finbench-sf01-rdf-serving-20260913-v2/rdf-profile-v2/profile.json`
- 配置SHA：`723e2517b160588a9c4e6c48e4f6a1b8694ee2e07cc8fc3aefa8f79bab6fe119`
- control SHA：`2591ac594fe0b88486bd88290e1f3a2f04ca6d9222d26621b65e343bf9caa150`
- audit SHA：`3b31468cf1aca454d20b219432d412ad61f5deb34c555a2df1f9153386f0f1af`

服务地址目前是明确未使用的离线占位，serving时需绑定实际自有端点；装载务必读取
`offline.rdf_loads`中的实际文件，不能把祖先`materialization_root`当作新control路径。
全量文件不会在请求时重写，catalog不会在runtime构建。

下一项只补正式每题观察预算和批次执行控制：tiny observer的256次是临时开发上限，
不能冒充正式预算，更不能跨题累计。设定共同wall/RSS/源流量等边界、每题独立计数、
失败分类/恢复和平衡顺序，再装载已冻结数据运行主评价。保留共享NL→FedX被tiny预算
截断的原观察，不为改善这条结果重新运行。完整服务/正式campaign仍未开始，
`formal_campaign_ready=false`；120组划分和原评价分母保持不变。
