# 计划内相同源读取已共享

2026-09-14，实现提交`33cd8b0`。[契约与多项式界限](../decisions/shared_native_reads_v1.md)。
新的strong模式在可行基础计划及可选候选打分前共享相同完整编译读取；没有新算子、
跨query缓存、模型权重调整或baseline变更。旧one-shot默认仍关闭这一优化。

11项新检查通过（0.47s）：包含平行边/自环的独立5节点8边图，两跳bag计数14保持，
两次相同读取降为一次；EXACT/PERFORMANCE都经可行基础计划与roots-only执行通过。
快照/参数/编译描述/预算/后端不同不共享，独立输出根及直接多输入端口保持；源失败
只尝试一次，所有依赖消费者失败或跳过。候选数量不增，legacy候选原样一致。

首轮12个检查中7通过、5失败：我把产物kind写成native，而真实编译产物标记为compiled，
因此优化未激活，答案仍正确但读取未减少。按实际契约修正后11项新检查全部通过；
首轮还包含1项受影响的已保存普通入口回放，已通过。没有因这次本地失败新增服务调用。

真实gate仅运行一次新的performance可信程序请求，关闭可选物理改进；估计器沿用冻结
版本，先产生可行计划，运行一个最终计划，无模型和候选试跑。8节点16关系使用既有
冻结Neo4j/Fuseki stores。对照项来自上一轮封存的coordinator记录，不重跑旧query。

|观察|旧完整读取|本次共享读取|
|---|---:|---:|
|源调用|14|11|
|源返回行|74|64|
|HTTP响应字节|18606|16399|
|独立gold行数|4|4，全部一致|

删除的三次读取对应`cq19→cq18`、`cq22→cq21`、`cq26→cq25`；全为相同Fuseki
完整查询。所有保留的11个artifact和返回行均与旧捕获逐一匹配，来源/快照身份相同。
各消费者仍有自己的规范化、字段和后续算子，不用去重来改答案重数。

本次online1541.514ms，其中联邦执行约1456.216ms，是另一冷服务会话；它不能与
前轮预热后145ms直接比较，也不作为共享加速或变慢的结论。确定收益是省去3次实际
重复调用和2207B响应，额外内存/长期性能还未评价。

本轮1最终计划、11源调用、0模型/fit/baseline/catalog build/数据重载/自动retry。
主句柄86651退出0；owned Neo4j81263与Fuseki81287均terminal，observer已停。
Fuseki退出143；Neo4j经既有SIGTERM/SIGKILL受限收尾退出-9。只清理了可重建的
本次serving copies，冻结输入和所有原始响应保留。

[原始receipt](/Users/anthonyche/xgap-data/shared-native-reads-20260914-v1/receipt.json)，
[完整strong结果与物理计划](/Users/anthonyche/xgap-data/shared-native-reads-20260914-v1/result.json)，
[逐请求对照及哈希](/Users/anthonyche/xgap-data/shared-native-reads-20260914-v1/analysis.json)，
[仓库证据索引](../../experiments/artifacts/shared_native_reads_20260914.json)。

检查与运行：

```bash
PYTHONPATH=src:tests:scripts /tmp/xgap-directed-tests.qU2YfW/venv/bin/python -m pytest -q tests/test_shared_native_reads.py
PYTHONPATH=src:scripts /tmp/xgap-directed-tests.qU2YfW/venv/bin/python scripts/check_shared_native_reads.py --output /Users/anthonyche/xgap-data/shared-native-reads-20260914-v1
```

下一项：审查已有源编译器能否支持把明确的单源过滤条件提前执行。当前请求的ID、
isBlocked和时间条件仍有在读取/Join后执行的路径；先检查类型、缺失值和共享消费者的
等价条件，再决定最小实现。保持toy-first，不重跑六步诊断或大题，不先改估计权重。
总体Goal未完成，02:00收尾暂停、10:00恢复的时段要求不变。
