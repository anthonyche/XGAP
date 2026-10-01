# 必要行条件提前执行已通过小图门

实现`15a24b8`；Cypher表达式组件门`d9cd497`。
[范围、证明与多项式界限](../decisions/source_row_prefilters_v1.md)。

新strong模式能将证明为必要的字符串/布尔相等条件，提前到完整源Match的外层执行。
原来的最终typed Filter、硬约束、字段、根和所有本地节点均保留；未知类型与缺失值
保守放行。共享读取在这一处理之后执行，只有过滤条件也相同的完整请求才共享。
不更改估计权重、不虚构选择率、不增加候选或调用，不改变baseline或legacy默认值。

14项新增定向检查首次通过（0.62s），2项受影响检查通过（0.33s）。覆盖真实进程内
SPARQL的多值属性、语言/日期/资源/缺失值、true与数字1、右列重命名、独立分支、
Limit/Aggregate屏障、绑定VALUES序列化，以及EXACT/PERFORMANCE的一计划小图链路。
未运行全套回归或大图。期间两次只读证据检查用错嵌套字段名，已按实际记录结构
修正；没有引发任何查询重跑，也不影响已封存的执行结果。

真实gate使用既有冻结8节点16关系Neo4j/Fuseki stores，仅运行一个strong可信程序
请求。三处证明：cq18/cq19的Account ID等于字符串1，cq24的isBlocked等于true。
cq18/cq19仍共享，所以实际增加过滤的源请求只有两个，均在Fuseki上。

|观察|前次共享读取|本次必要过滤|
|---|---:|---:|
|源请求|11|11|
|源返回行|64|61|
|HTTP响应字节|16399|15820|
|独立gold|4行|4行，全部一致|

Account返回4→1行，减少3行；两个Medium原本都为true，仍返回2行。九个未变artifact
返回行逐一与旧捕获相同；两个改写artifact返回行均为旧结果子集。运行拓扑、全部
本地节点、快照身份及最终答案与旧记录一致。这是具体的通信节省，不是速度优势证明。
本次另一冷会话online1373.498ms、执行1289.585ms，仅记录，不与旧预热数据比较。

因为新增guard没有落到Neo4j上，另声明并执行一次只读六行Cypher表达式组件检查：
字符串、布尔、数字、日期及null同场出现。实际保留a/d/e/f，最终typed过滤只保留a，
与独立预期一致；1次查询，无图数据写入。这证明新增Cypher语法和类型分支可执行，
不伪称是另一个联邦问题结果。

合计12次源查询（11整体+1组件），0模型/fit/baseline/catalog构建/数据加载/自动retry。
主句柄38951、86174均退出0；两个会话的全部owned进程组terminal，observer已停。
整体门Neo4j83717/Fuseki83739；组件门Neo4j84077/Fuseki84099；Fuseki均退出143，
Neo4j均按现有受限SIGTERM/SIGKILL收尾退出-9。仅清理本次可重建serving copies。

[整体原始receipt](/Users/anthonyche/xgap-data/source-row-prefilters-20260914-v1/receipt.json)、
[逐请求比较](/Users/anthonyche/xgap-data/source-row-prefilters-20260914-v1/analysis.json)、
[Cypher组件receipt](/Users/anthonyche/xgap-data/necessary-filter-cypher-20260914-v1/receipt.json)、
[证据索引](../../experiments/artifacts/source_row_prefilters_20260914.json)。

复现本轮必要边界的入口（已有结果不重复运行）：

```bash
PYTHONPATH=src:tests:scripts python -m pytest -q tests/test_source_row_filters.py
PYTHONPATH=src:scripts python scripts/check_shared_native_reads.py --check-prefilters --output NEW_OUTPUT
PYTHONPATH=src:scripts python scripts/check_necessary_filter_cypher.py --output NEW_COMPONENT_OUTPUT
```

下一门：审计普通发布入口的准备/计时与实际规划是否一致，优先消除已观察到的重复
冻结依赖加载；采用明确的每请求快照生命周期，不引入跨请求答案缓存。只针对新风险
做本地检查和已有结果回放，无需再次启动后端。论文模式发布与开放NL/模式优势仍未证明。
02:00总结暂停、10:00恢复的用户时段不变。

MaterialPassport: development diagnostic; exposed tiny fixture; pinned source/answers;
no statistical generalization, estimator training, baseline alteration or paper score.
