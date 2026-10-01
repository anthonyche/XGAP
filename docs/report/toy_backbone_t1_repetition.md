# T1：可选路径与有限重复

2026-09-11。原生数据库 gate 与完整回归均通过，本有限重复步骤已验收。
基于已提交的 d9c2858；本步骤不代表完整 T1 或整个系统已完成。

原实现已经接受 Optional/Bounded 的语法，却在逻辑 lowering 中直接拒绝。
现在 Optional 使用 Nodes 与子表达式的 Union；有限 Bounded 对允许次数的
子路径拼接取并集，再用已有的一步 Recursive 执行路径模式约束。没有新增
底层代数算子，也没有改变现有算子的含义。解析器同时修复了合法上界 0 被拒绝。
能力检查反映实际逻辑支持，后端仍独立检查原生执行范围。

两个容易产生错误答案的区别已有直接证据：重复次数不等于边数；最短路径必须
在允许的重复范围内选择，不能先选全局最短再删掉不满足下界的路径。
正次数重复的 nullable 子路径可以产生零长度答案，并参与最短选择；独立的
零次重复 Nodes 分支则放在正次数最短选择之外，与既有 Star 一致。
形式定义与限制见 [语义决定](../decisions/finite_regex_repetition_v1.md)。

## 独立完整链与真实结果

复用冻结的 5 节点、8 边图；原 18 题和所有旧 gold 不变。新增 13 题均有
人工指定 NL、gold PathPatternQuery、逻辑树、独立 Cypher/SPARQL 查询以及完整
路径身份答案；未将生产编译器或 evaluator 输出写成 gold。Fixture 位于
`datasets/backbone_repetition_v1/`，其目标查询直接表达预期路径及最短选择。

| 查询 | 覆盖行为 | 每个后端的正确答案数 |
|---|---|---:|
| R01 | Optional 包括零长度与一步 OUT | 4 |
| R02 | Seq 中 Optional IN，保留两条平行边身份 | 3 |
| R03 | 恰好重复零次，孤立节点保留 | 1 |
| R04 | 恰好两次的 SHORTEST，不被一步路径抢占 | 2 |
| R05 | 一次可变长度子路径，可以含一边或两边 | 3 |
| R06 | 可变长度有限范围内选最短 | 1 |
| R07 | TRAIL 拒绝两次使用同一自环边 | 0 |
| R08 | WALK 允许两次使用同一自环边 | 1 |
| R09 | 正次数 nullable 子路径的零长度最短答案 | 1 |
| R10 | 独立零次分支与正次数最短自环同时保留 | 2 |
| R11 | WALK 的嵌套有限重复接 IN | 2 |
| R12 | 显式 query depth 补足上界，SIMPLE 拒绝重复自环 | 0 |
| R13 | 无向两步 TRAIL 只保留不同平行边组合 | 2 |

真实 Neo4j 5.26.30 与 Fuseki 5.6.0：**26/26 生产编译执行、26/26 独立
目标查询答案正确**；原 Neo4j 路径＋Fuseki 属性过滤＋coordinator join 的
两后端 slice 继续得到 Alice→Cara。测试分别执行生产路径和独立目标，并核对
完整路径身份，不以行数相同代替正确性。新语义 DAG 入口另由 13 个本地 RDF
执行用例验证；未把它称为本轮全部 26 次原生运行的入口。

本轮查询调用为 26＋26＋2＝54，加载与健康检查另计。两个 owned 服务均正常
停止，无强杀升级；没有失败外部动作重试。记录的 15 个源码、42 个旧 fixture
文件和 28 个新 fixture 文件哈希均与验收时工作区一致。未使用 LLM、GPU、
GrailQA 原始语料或 catalog 构建。

## 验证与复现

- 新模块 35 项覆盖完整链、五种模式、最短选择与外层过滤顺序、嵌套作用域和
  既有原生展开预算。Focused 226 passed / 4.30s，interface 42 passed / 1.89s。
- Daily 原 session7181 exit0：**335 passed / 15.12s**，原 18 题 demo 正常。
- Native 原 session50965 exit0；上述 52 个答案对照与原 slice 全部正确。
- Broad 原 session81593 exit0：**3,180 passed / 38 skipped / 645.66s**，
  全部 24 个 harness/example 入口通过。源码在启动前稳定，后续仅更新文档。
  所有本轮测试/原生进程已终止，不再轮询或无新变化重复验收。

复现入口为 `scripts/run_toy_development.sh`、
`scripts/run_toy_backbone_native.py --repetition --execute`（需显式 runtime/output/Java 参数）
和 `scripts/run_acceptance.sh`。本轮使用 Python 3.10.19、RDFLib 7.1.4、Java 21。
持久化摘要 `experiments/artifacts/toy_backbone_t1_repetition_20260911.json`。
原始结果 `/Users/anthonyche/xgap-data/t1-repetition-native-20260911/result.json`；
日志 `/tmp/xgap-t1-repetition-{focused,interface,fast,native,acceptance}.log`。

Native 仍限制现有 128 分支/64 边预算；只在 WALK 下展开嵌套有限重复。
嵌套非 WALK 的局部限制不能被静默展开抹掉。没有显式有限 query depth 的
下界 ≥2 无界重复，以及其他未支持递归组合仍是明确缺口。更广 typed 聚合、
排序、通用源划分与流式执行也不由本步骤解决。

这组结果证明小图上的实现与声明语义一致，不证明 NL 准确率、规模性能、
memory 收益或 SOTA 优势。后续继续同图修复设计缺口，再验收 T2 的离线
catalog 冻结/runtime 只读、两条测试链与最小 replay，最后做真实评价。
