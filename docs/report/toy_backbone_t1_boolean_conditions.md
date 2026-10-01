# T1：原生布尔条件与缺失属性语义

2026-09-11，基于已提交 bafce8e；本布尔条件步骤已通过真实分项和最终完整回归，验收完成。
本步补齐现代路径编译与 Match 的 AND/OR/NOT，保留既有参考语义与原始图/gold。
整个 T1、T2/T3 与系统 Goal 仍未完成。

## 实现与原因

Cypher 对原子比较先处理 null，再执行 NOT。SPARQL 把属性读取放在每个原子
EXISTS 内，避免 OR 的一边缺失属性时整行被 mandatory triple 删除。
因此 `score != 1` 在缺失属性时仍为 false，`NOT(score = 1)` 则为 true。

既有 Python scalar equality 保留 True=1、False=0；数值排序排除 bool、字符串
及非有限数。Cypher 的有限范围检查采用上下界，避免 abs(最小64位整数) 溢出。
这是维持原定义，不是另建一套严格类型相等语义。RDF 标量仍要求显式、单值映射。

现代 Match 共享条件 renderer 与零节点 shape，RDF 显式节点 domain 在条件之前
绑定。每个布尔叶子继续检查类型、位置、映射和底层能力。Match 还保留原来
Nodes/Selection 的显式能力准入。冻结的 M9 策略仍有自己的有限能力边界。

SHORTEST 的条件放置检查遍历整棵布尔树。端点条件可以提前；独立长度合取继续
使用最终长度过滤；长度位于 OR/NOT 内时由已验收的 scoped planner 先选最短，
再与完整路径候选做交集。不能通过提前过滤而把较长路径提升为“最短”。

## 独立预期与可见结果

`datasets/backbone_boolean_v1/` 是原 5 节点/8 边结构的独立属性 overlay。
20 道完整 NL→gold query→逻辑树→独立 native target→完整路径答案；4 个 Match
程序还有显式类型答案和 8 个独立目标。计划与答案未从待测实现输出生成。
原始 18 题、旧 graph/load/gold 均不变，原两引擎 slice 始终保留。

| 例子 | 独立预期 | 说明 |
|---|---|---|
| score = 1 | a、b、c | integer1、double1.0、true 按既有规则相等 |
| score != 1 | d | 缺失属性不满足原子不等式 |
| NOT(score = 1) | d、z | 缺失属性在外层 NOT 后为 true |
| score = 1 OR note = open | a、b、c、d | 某个属性缺失不会消灭另一分支 |
| 数值 score > 0 | a、b | bool 与字符串不参加数值排序 |
| NOT 数值 score > 0 | c、d、z | 原子判断为 false 后正常取反 |
| Alice→Cara 的最短路径，再要求长度2或3 | 空 | 一步最短先被选择，外层过滤不能提升长路径 |
| floor >= -9223372036854775808 | a | 有符号整数最小值不会因有限性检查溢出 |

初版内部位置条件使用了 variable-length recursion，而当前 semantic validator
只允许固定长度上的数字位置；该探索项保留在 `rejected.json` 作负向回放。
当前 C17 为 NOT Ghost 的零路径测试。没有放宽原始准入，也没有把拒绝当成已
实现。任意可变长位置谓词仍是完整 T1 的缺口。

## 真实数据库与成本

首轮原生 session18573 exit0：**40/40 路径程序、40/40 独立路径目标，8/8 Match
执行、8/8 独立 Match 目标，3/3 规划程序及6/6候选答案，原两后端 slice 正确**。
路径实际44次远程调用，独立路径40次；Match/对照各8次；规划8次观测＋4次
serving，额外候选验证4次；原 slice 2次。两 owned 服务正常停止，无强杀或
失败外部动作的自动重试。结果：
`/Users/anthonyche/xgap-data/t1-boolean-native-20260911/result.json`。

随后的日常测试发现 Match 迁移遗漏了显式 Nodes 能力拒绝；补回 Nodes 与
Selection 准入，查询条件文本不变。针对受影响 Match、规划和原 slice 做
`--boolean --boolean-followup-only` 验收，不重复已通过的40＋40路径目标。
最终 follow-up session71425 exit0：8/8 Match、8/8独立对照、3/3规划程序、
6/6候选与旧 slice 均正确。8次观测＋4次serving，额外候选验证4次及旧slice2次
单列；Match/对照各8次。两个 owned 服务均正常停止。
结果 `/Users/anthonyche/xgap-data/t1-boolean-followup-native-20260911/result.json`。

原生记录包含31个源码、42个旧fixture、56个新fixture文件哈希。首次记录与最终源码差异为 runner、Match 准入和 directed.py 的依赖符号恢复；
follow-up 与最终源码仅 directed.py 的符号恢复不同。原生查询 renderer 未因此
改变。最终离线重编译40条路径计划＋8条Match计划，与已成功真实执行的完整计划
逐一比较，**48/48 完全相同**；该比较没有再次调用数据库。后续数据适配器的
显式布尔拒绝由本地140项依赖测试验证，不以本次小图原生结果冒充其完整支持。

## 本地验证和失败保留

- 兼容性115 passed/4.14s；新扩展最终 focused296 passed/15.96s。
- 首批新测试11 failed/21 passed：独立 RDF 最短参考、bool 显示格式、Match 的
  global entity ID 与 double encoding 夹具问题。参考查询改为独立的“排除更短
  连通路径”表达；保留答案，修正映射/预期接口。两个中间本地gate各4 failed/28 passed。
- 随后 focused3 failed/294 passed：可变长数字位置拒绝及两个过期 OR/NOT 拒绝
  断言。保留前者负向输入、迁移后者，再获296 passed。
- 首次 daily1 failed/398 passed，暴露上文 Nodes 准入回归。第一次补丁测试因
  import 来源写错出现2个 collection errors；修正后准入回放71 passed/2.88s。
- 最终 daily session67642 exit0：401 passed/25.98s，原18题demo正确。
- 第一 broad session65353 exit2，在收集阶段发现旧 Freebase adapter 导入
  `_OPERATORS` 失败（2 collection errors/1.07s）。恢复原符号，并显式保留旧适配器
  的合取边界，避免共享 shape 扩展后 OR/NOT 被静默忽略。没有运行大数据任务。
- 本地依赖回放 session5669 exit0：140 passed/3.88s。原生计划一致性48/48通过。
  最终 broad session69433 exit0：**3,246 passed / 38 skipped / 670.40s**，
  全部24个harness/example入口通过。日志 `/tmp/xgap-t1-boolean-acceptance-final.log`。
  第一 broad 已权威终止；新运行因修复代码而启动，不是因观察超时重启。

本轮只测系统正确性与接口/规划连接。没有模型调用、catalog build、大数据扫描
或新的论文性能结果；未主张无界递归、所有类型/多值RDF、一般源划分、端到端
自然语言准确率。下一步补齐剩余 typed 聚合/排序及路径覆盖，再推进 T2。

下一步已有具体本地观察：当前 SUM 把整数9007199254740993转成浮点后丢失精度，
RDF decimal 无法进入该聚合；nullable 排序与混合类型分组也未闭合。这些是在
现有 coordinator 上的零外部调用定位，不是本次布尔条件已解决的能力。后续先
明确 binding 层的类型/空值约定，再以独立 typed gold 与双后端组合修复。

持久化验收摘要：`experiments/artifacts/toy_backbone_t1_boolean_conditions_20260911.json`。
最终 broad 启动后未改生产源码或测试；原始图/gold与新属性fixture哈希均核对一致。
所有本轮 native/test 进程都已终止，不再重复已通过的运行。
