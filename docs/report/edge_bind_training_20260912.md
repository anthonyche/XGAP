# 边 bind 的实际执行与冻结估计覆盖已补齐

本轮只处理上一轮真实发现的缺口：新边bind计划虽然可编译，原模型却没有对应工作类别。
现在4个独立端点bind训练计划在真实Neo4j/Fuseki上全部正确，复用旧28份观测并冻结了
新的32样本模型。三类金融查询的6个合法计划现均可估计。没有重跑那三条金融查询。

## 新增工程

训练使用独立namespace中的4个Vertex、6条LINK，两条边的端点和值相同但身份不同。
4个计划在启动服务前固定；source绑定1个key，target绑定2个key。每个训练计划只执行
自身的两个远程fragment，不试跑其他策略选优。模型接口增加按样本的冻结统计映射，
不同图保留各自snapshot和记录尺度；不冒充同一来源。旧模型schema、特征维度、既有
调用默认语义及训练记录不变。新模型另存，固定128轮离线fit一次，不搜索参数。

[范围、RQ/X/Y及复杂度契约](../decisions/edge_bind_training_v1.md)。新拟合保持有界
O(SNd)；这不是查询执行时间界，也不是估计精度/质量保证。

## 实际结果

| 预先指定的训练计划 | 实际返回的边 | 最终源调用 | Scheduler单次耗时 |
|---|---|---:|---:|
| Neo4j source bind | et_1、et_2、et_3 | 2 | 221.416ms |
| Fuseki target bind | et_1、et_2、et_6 | 2 | 77.238ms |
| Neo4j target bind | et_1、et_2、et_6 | 2 | 74.690ms |
| Fuseki source bind | et_1、et_2、et_3 | 2 | 50.994ms |

四份实际结果均与独立列出的边身份/权重一致；平行边保留。没有新warmup或重复轮次，
首次查询效应原样计入，这些数字只说明训练与执行覆盖，不能作为稳定延迟对照。

[完整收据](/Users/anthonyche/xgap-data/edge-bind-training-native-20260912-v1/receipt.json)；
[新冻结模型](/Users/anthonyche/xgap-data/edge-bind-training-native-20260912-v1/frozen_work_estimator.json)。
模型content hash为`ccc9f468d37d6d4a1e404dc8170f5081c45bae25263416a895ae93acacd2ca94`；
文件SHA-256为`80c3dc09856d1379b1bc28c63de19f23f42a2931b101926b83d334cc21322873`。
`parent_import.json`封存旧collection/manifest/28measurement哈希，并还原原training sample
哈希；旧金融答案/实测时间不是训练输入。`manifest.json`固定新程序/顺序/统计和排除集合，
各`new-*/measurement.json`先保存实际artifact/结果，再写独立correctness评价。

三项新风险检查已通过。初次检查发现新fixture缺显式RDF term mapping；补齐后又发现
单元测试的query ID与计划metadata不一致，修正后通过。只补跑失败项；旧28条import
检查和通过后的新检查不重复。单元测试的2个analytic标签只测试接口，不进入native模型。

新增采集8次源调用、429.304ms；旧观测46次调用、852.007ms从文件复用，新增执行为0。
另有本轮3次fixture装载（363.144ms）及服务启动（7343.411ms），health单列；fit一次
28.638ms。原收据保留历史collection成本，`collection.json`明确新增/复用边界，不能
把复用成本重复算作本轮在线查询开销。旧模型fit及warmup成本仍在原报告中，未再次发生。
模型、baseline、当前金融查询执行与自动retry均0；Neo4j33935/Fuseki33976均已终止。

## 可以得出和不能得出的结论

模型冻结后，只重新编译原已保存金融语义程序并预测，零源调用、零当前题实测标签读取：
F1/F2/F3由各3/6可估计变为各6/6。这消除了已知工作类别缺失，补齐了真实端点bind接口
到冻结估计器的连接。原模型仍保留；新模型到金融图的deployment显式声明未经校准。

不能据此宣称选中了实际最快计划、排名改进、两模式Pareto优势或任何baseline提速。
没有用当前金融题试跑最优计划来训练，也不为更好的回归误差再拟合一次。

下一步是冻结金融source schema/catalog/profile并执行一次普通NL-only请求，使用本轮
新模型。现有金融provider与参数v2接口已实现；实际金融NL链路仍未验收。继续toy-first，
不重跑旧金融成功门禁，不启动大数据campaign或baseline优化。真实样本/reference/金额
精度约定/预算随后冻结；Sep14 17:00核心目标、Sep18真实结果目标及active Goal保持。
