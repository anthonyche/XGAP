## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: run
- Origin Date: 2026-09-14
- Verification Status: UNVERIFIED
- Version Label: practical_cost_diagnostic_v1

上面的状态不表示六次执行未检查：执行、gold和资源收尾均已核对；统计泛化与独立
重复验证未进行。这里报告一次有界工程诊断，不形成论文总体或显著性结论。

## 固定小图成本诊断已完成

提交`1467b4b`。先做离线预检，再按[预先固定的协议](../decisions/practical_cost_diagnostic_v1.md)
在同一Neo4j/Fuseki会话执行六个步骤。8节点16关系、同一个确定性gold查询，三种计划
均保留完整语义。每次一个预定最终计划，不把实测赢家反馈给当前query的planner。

|计划|冻结估计/ms|首次顺序执行/ms|第二次反向顺序执行/ms|源调用/次|源行/次|响应B/次|
|---|---:|---:|---:|---:|---:|---:|
|coordinator完整读取|28.933|1257.357|144.801|14|74|18606|
|首跳anchor fanout|297.949|248.355|169.345|14|62|17157|
|逐跳progressive binding|717.281|348.627|174.270|14|51|16252|

所有六次均得到4行、与独立预写gold完全一致。第二序列里，冻结估计器的顺序与观察
一致：coordinator、首跳、逐跳。毫秒数并不准确，但用户要求的相对排序在这一例中
没有出错。不能从此例推断一般排序准确率；每计划只有一个第二序列观察，仍有顺序、
共享缓存和机器状态影响。首轮不是三个彼此独立的冷启动，不据此比较谁快。

观察说明：逐跳确实减少源返回行与字节，但本例没有减少调用数，额外绑定和串行依赖
没有带来更短总时间。现有证据不支持为了让逐跳胜出而修改估计权重。模型717ms分数
的主要项为Neo4j bound-call约445ms、bound-record proxy约213ms、bound-column proxy
约24ms；这只是冻结公式的分解，权重与粗工作量并非真实逐项耗时。
三个计划均超出多项训练数值范围，迁移没有校准保证。

另一个已保存的live槽位请求仍为812.198ms：信息获取497.617ms（61.3%），strong搜索
46.093ms（5.7%）。在其他成本完全不变的假设下，去掉全部搜索的算术上限仅约1.060倍。
这解释了为什么单独收紧planning预算不足以保证PERFORMANCE大幅提速；不是新实测收益。

## 成本、失败与证据

新源调用总数84；0模型、0fit、0baseline、0catalog build、0数据重载、0自动重试。
已有冻结stores被校验和复制，服务准备5957.256ms单列；首序列查询总1854.338ms保留，
未从成本记录里删除。第二序列成本也完整保留。源节点可能并行，不能把它们的elapsed
相加当成query wall time。只比较原始观测，不做均值、CI或显著性外推。

主进程句柄93589退出0；两个owned服务均terminal，observer关闭，无残留资源组。
Fuseki退出143，Neo4j在收尾SIGTERM后由既有受限清理流程SIGKILL，退出-9；只删除
本次可重建的serving copies，原冻结输入、查询、响应与日志均保留。

[原始receipt](/Users/anthonyche/xgap-data/practical-cost-diagnostic-20260914-native-v1/receipt.json)，
[封存计划、顺序与全部估计](/Users/anthonyche/xgap-data/practical-cost-diagnostic-20260914-native-v1/intent.json)，
[逐项分析与哈希](/Users/anthonyche/xgap-data/practical-cost-diagnostic-20260914-native-v1/analysis.json)，
[仓库索引](../../experiments/artifacts/practical_cost_diagnostic_20260914.json)。

运行命令：

```bash
PYTHONPATH=src:scripts /tmp/xgap-directed-tests.qU2YfW/venv/bin/python scripts/diagnose_practical_costs.py --output /Users/anthonyche/xgap-data/practical-cost-diagnostic-20260914-preflight-v1
PYTHONPATH=src:scripts /tmp/xgap-directed-tests.qU2YfW/venv/bin/python scripts/diagnose_practical_costs.py --output /Users/anthonyche/xgap-data/practical-cost-diagnostic-20260914-native-v1 --execute
```

## 下一处工程风险

coordinator的14个源节点中发现3对相同后端、相同完整query artifact（仅artifact_id不同）
的无依赖读取：`cq18/19`、`cq21/22`、`cq25/26`。现有计划分别调用并保留结果。
下一门研究在相同冻结快照和确定性完整读取范围内共享这类重复源读取，保持每个
消费者的绑定与bag语义。静态候选可望14→11调用，实际效果须经tiny新风险门验证；
不共享不同快照、绑定参数、编译语义或预算的请求，不加跨query结果缓存。
这直接处理已观察到的重复调用；不继续调估计器或重复这组六次测量。
