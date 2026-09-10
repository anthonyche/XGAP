# T1：语义能力要求接入实际规划与执行

2026-09-10。真实小图 gate 与完整回归均通过，本能力准入步骤已验收。

原实现对任何非空 required_capabilities 都直接拒绝。现在编译器先完成纯编译，
再将要求绑定到该语义操作实际生成的原生或 coordinator 节点；所有要求满足后
才返回可供观测、选择和执行的计划。已有 native profile、编码和查询形状限制
继续生效，不因声明能力而跳过检查。

例如，C01 要求 paths 使用 Cypher、people 使用 SPARQL、Join 由 coordinator
完成。这会从原四个等价位置组合中保留 Neo4j paths＋Fuseki people；C08 保留
反向分工。coordinator.join 不能由另一个操作的 join 满足，原生 Cypher 能力也
不能从其他源“借用”。未知名字明确失败，不删除要求或更换语义。详情见
[能力准入决定](../decisions/semantic_capabilities_v1.md)。

## 小图结果

八个显式 overlay 复用已有完整 NL→semantic DAG/PathPatternQuery→预期执行
计划→独立 target query→typed result 链。原 5 节点/8 边和全部旧 gold 不变。
新增文件只声明能力要求与人工列举的允许位置，不把实现输出保存成预期答案。

| 用例 | 主要要求 | 保留候选 | 排除候选 | 所有保留候选答案 |
|---|---|---:|---:|---|
| C01 | Cypher 路径＋SPARQL 属性＋coordinator join | 1 | 3 | 正确 |
| C02 | coordinator aggregate/order/filter | 4 | 0 | 正确 |
| C03 | SPARQL anchor＋Traverse 的 semi-join | 2 | 2 | 正确 |
| C04 | filter/union/project，共享 Match | 2 | 0 | 正确 |
| C05 | RDF read＋空输入全局 count | 1 | 1 | 正确 |
| C06 | 属性图/RDF read＋align/equality join | 1 | 3 | 正确 |
| C07 | join 列冲突与 legacy equality_join 别名 | 4 | 0 | 正确 |
| C08 | SPARQL 路径＋Cypher 属性＋coordinator join | 1 | 3 | 正确 |

真实 Neo4j/Fuseki：**8/8 查询成功，16/16 保留候选答案正确，12 个位置被按预期
排除**；原两后端 vertical slice 继续正确。20 次观测＋14 次 serving＝34 次调用；
为验证其他候选额外执行 15 次，旧 slice 2 次，分别计入记录。加载与健康检查另记。
被排除位置不会注册自己的观测/执行动作。此候选减少来自显式执行要求，不是
memory 学习效果或优化性能提升的证据。

本轮重用冻结的 typed gold 并执行实际生成查询；独立原生目标的先前验证记录见
[语义 DAG 报告](toy_backbone_t1_semantic_dag.md)，未宣称本轮重跑了那些目标。

## 验证与边界

- Focused **120 passed in 3.51s**，session8138 exit0；包括新模块 28 项，
  测试拥有者隔离、错误能力/数据模型、原编译器拒绝仍有效、全部允许位置和
  实际 RDFLib 观测→选择→执行。RDFLib 是独立本地求值，不冒充 Fuseki 服务。
- Daily **300 passed in 13.51s**，session47096 exit0；原 18 题 demo 正常。
- Native session34608 exit0：8/8 查询、16/16 候选与原 slice 正确。两个 owned
  服务均正常停止，无 kill escalation，无重试；记录的源文件哈希与当前一致。
- 完整回归原 session91696 exit0：**3,145 passed / 38 skipped in 667.51s**，
  全部 24 个 harness/example 入口通过。日志
  `/tmp/xgap-t1-capabilities-acceptance.log`。所有本轮进程已终止；启动后生产源码
  没有继续变化，未重复已通过验收。

原始结果：`/Users/anthonyche/xgap-data/t1-capabilities-native-20260910/result.json`。
持久化摘要见 `experiments/artifacts/toy_backbone_t1_capabilities_20260910.json`。

能力准入只证明当前具体编译方案满足声明的静态执行要求；后端健康、运行成功和
模型质量仍分别验证。它不支持任意领域能力名，不把 window_total 等同于普通
aggregate，也不增加缺失操作来满足装饰性声明。完整 T1 的剩余 path/typed
semantics、T2 catalog freeze/runtime/replay 和 T3 真模型/评价仍未完成。

用户新指令：本 milestone 完成后暂停开发，北京时间 **2026-09-11 10:00** 恢复。
已调整现有 xgap 定时任务至下一次上午 10 点；届时恢复后续 toy-first 工程。
