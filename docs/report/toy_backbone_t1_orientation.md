# T1：方向语义与逻辑参考链闭合

2026-09-10。原来的 IN 已能原生执行，但旧 M5 逻辑层缺少表达反向路径的操作。
本轮按独立语义设计增加 **XGAP Reverse 扩展**，让逻辑参考链能够表达 IN，
并把无向边接到已有有界原生编译器。原图和所有原始 gold 文件保持冻结。

原 **18/18** 小图答案与显式更新的逻辑预期通过。新增九个方向用例在真实
Neo4j/Fuseki 上 **18/18** 编译执行、**18/18** 独立原生对照正确，原两后端
slice 仍通过。最终共享核心验收 **3,117 passed / 38 skipped in 662.26s**，
24 个 harness/example 入口通过。此方向步骤已验收；完整系统 Goal 仍未完成。

## 语义与实现

`Reverse(P)` 将每条交替 node/edge 序列反转，保留边 ID、属性和原图的
source/target 存储。零长度路径不变，反转两次得到原集合。Union 与反转
可交换；反转 Join 的结果等于按相反顺序连接两个反转后的输入。

这是明确标注的 XGAP 方向扩展，不重新定义原 `Edges(G)`，也不声称给原论文
代数增加了一个已有算子。见 [版本化语义决定](../decisions/path_orientation_v1.md)。
反转只接受 PathSet；不能隐式反转 SolutionSpace 排名或 binding rows。

IN 降为过滤后的正向边集合再 Reverse；UNDIRECTED 降为正向集合与其 Reverse
的 Union。于是自环的两个方向按完整路径去重，平行边因 ID 不同仍分别保留。
外层条件按遍历后的节点/边位置求值。原 WALK/TRAIL/ACYCLIC/SIMPLE/SHORTEST
规则不变；同一边走两个方向仍重复同一 ID，不能通过 TRAIL。

原生编译把每个 UNDIRECTED 边展开为 OUT/IN 两种选择，并计入原分支预算。
后续复用现有方向编译、PathSet 去重与 selector。老 M9 编译器明确拒绝
Reverse，不会将它误编译成 OUT；新的有界原生入口已具有真实执行证据。

## 结果长什么样

| 用例 | 意义 | 每个后端的完整答案数 |
|---|---|---:|
| D01 | Bob 反向一步，保留两条平行边 | 2 |
| D02 | Bob 先 IN 再 OUT 到 Cara | 2 |
| D03 | Dan 的无向自环去重 | 1 |
| D04 | Bob 任一方向一步 | 4 |
| D05 | Bob 无向 WALK 正闭包，最多两步回到 Bob | 6 |
| D06 | 同上，改为 TRAIL | 2 |
| D07 | 同上，改为 ACYCLIC | 0 |
| D08 | 同上，SHORTEST 保留所有最短正长度环 | 6 |
| D09 | 孤立 Zoe 的 IN Star 含零长度路径 | 1 |

例如，`b/e1/a/e1/b` 只使用一条物理边往返，WALK 接受而 TRAIL 拒绝。
`b/e1/a/e7/b` 和 `b/e7/a/e1/b` 分别用了两条不同的平行边，TRAIL 均接受。
这些用例对照的是完整路径，不是只核对端点或行数。零结果 D07 有独立语义
预期，不用空集掩盖执行失败。

原 T15 的逻辑文本是 semantic Traverse 占位。新增
`datasets/backbone_orientation_v1/legacy_logical_plans.json` 提供独立编写的
可执行逻辑预期，开发测试与 demo 显式选择它；旧文件和两个预期答案完全不变。
CLI 通过 `--logical-expectations` 选择该版本。编译器不读取任何 gold。

## 验收记录

- 初次 focused 在收集阶段因测试导入了未公开导出的 GroupKey 而失败；无查询
  运行、无外部失败。修正导入后 **212 passed in 9.35s**（session11123）。
- 较早日常 gate **180 passed in 12.10s**（session58672），含五种递归模式
  下反转等价性；原十八题 demo 的逻辑预期与完整答案全部正确。
- 显式选择逻辑预期版本的 offline CLI 验收也通过：18/18 logical plans、
  18/18 reference answers、18/18 independent SPARQL targets，session63085 exit0。
- Native session67522 **exit0**，Neo4j5.26.30/Fuseki5.6.0，Java21；十八次
  编译执行、十八次独立目标和两次旧 slice 调用分别记录。两 owned 服务正常
  停止，无强杀、无重试。记录的源码及原图/新 fixture 哈希与当前文件一致。
- 首次 broad session61777 exit1：**3 failed / 3,114 passed / 38 skipped
  in 670.13s**。发现候选能力评估器仍硬编码“IN/UNDIRECTED 不支持”，与实际
  lowerer 不一致。已修正为版本化 `m5_path_algebra_orientation_v1`；仍保持
  `backend_execution_verified=false`，M9 原生限制由独立编译检查确认。
- 相关候选评估、grounding、重建和执行入口回放最终 **261 passed / 20 skipped
  in 3.18s**（session14689），中间旧断言失败保留日志；没有跑真实 GrailQA。
- 最终 broad acceptance 原 session96124 **exit0：3,117 passed / 38 skipped
  in 662.26s**，24 个 harness/example 入口通过，日志
  `/tmp/xgap-t1-orientation-acceptance-final.log`。原生方向代码未改动，故未重复
  已通过的真实数据库 gate。所有本轮进程已终止。
- 随后只调整日常 harness 接线，将候选能力一致性测试纳入快速循环。最终
  **272 passed in 12.56s**（session97917 exit0），十八题 demo 正常。
  日志 `/tmp/xgap-t1-orientation-fast-with-capabilities.log`。最终 broad 启动后
  生产源码未改动，不为此单独重复完整回归。

真实原始结果：`/Users/anthonyche/xgap-data/t1-orientation-native-20260910/result.json`。
随仓库保存的 [验收记录](../../experiments/artifacts/toy_backbone_t1_orientation_20260910.json)
含逻辑预期迁移、实际编译计划、完整路径、原生指标及版本哈希。
本地日志前缀 `/tmp/xgap-t1-orientation-`，后缀为 `focused-initial.log`、
`focused2.log`、`fast-final.log`、`native.log`。

## 结论与剩余边界

IN 的逻辑参考缺口已由可组合操作闭合；新无向路径行为同时得到独立参考和
真实后端验证。原始图、边身份及递归规则没有被改成方便通过测试的另一套定义。
这是 correctness 证据，不是模型准确率、优化性能或大数据实验结果。

语义 DAG 中额外 required_capabilities 的准入、嵌套/无界原生递归、
Optional/Bounded 等更多 AST 组合、广泛 typed aggregate/
order、catalog 完整生命周期、统一 failure replay、真实模型与大集评价仍需
继续。按照 Goal，开发继续用小图和模块＋vertical slice；大数据只用于后续
真实集成与正式评价，不回到 GrailQA 高成本开发循环。
