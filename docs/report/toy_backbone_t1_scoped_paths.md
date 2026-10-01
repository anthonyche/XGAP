# T1：有限嵌套路径的作用域执行

2026-09-11，基于已提交的 861e043。真实数据库分项、最终本地 gate 和完整
回归均通过，本有限嵌套作用域步骤已验收；整个 T1 和系统 Goal 仍未完成。

原生展开无法统一过滤嵌套表达式：`Seq(TRAIL(P), Q)` 只限制 P，不能把该
限制改施加到 P 与 Q 拼接后的整条路径；局部 SHORTEST 也必须先选最短，
再处理外层条件。新执行计划保留这些边界，以支持的原生子表达式为输入，
在 coordinator 执行已有路径拼接、Union 和 Recursive。共享子表达式只执行
一次。原来能用单个原生查询执行的计划继续走原有路径。

外层 source/target/条件由独立编译的有限 WALK 候选集合表达；最后按完整
路径身份做 semi-join，再应用原 selector。构造候选集合之前校验原查询，
避免替换 mode/selector 掩盖非法输入。执行器只消费数据库返回的路径，不
加载 toy graph/gold 求答案，也未新增底层代数算子或改写已有含义。见
[设计决定](../decisions/scoped_path_execution_v1.md)。

## 新增的完整预期链

冻结的旧 5 节点/8 边图、原 18 题及全部旧 gold 不变。新 15 题有独立 NL、
PathPatternQuery、逻辑树、原生查询、完整身份答案与预期调用数，位于
`datasets/backbone_scoped_v1/`。目标查询使用独立关系子查询与每层最短聚合，
不调用生产编译器；逻辑树与答案均未从实现输出生成。

| 用例 | 要验证的区别 | 每个后端的答案数 | 每个计划调用数 |
|---|---|---:|---:|
| N01 | TRAIL 子路径之外可以再次使用自环边 | 1 | 3 |
| N02 | ACYCLIC 在子路径内排除自环 | 0 | 3 |
| N03 | SIMPLE 的作用域不扩大到外层 Seq | 1 | 3 |
| N04 | 子路径内 SHORTEST，之后再拼接 | 1 | 3 |
| N05 | 整体再施加 TRAIL 时排除重复边 | 0 | 3 |
| N06 | Optional 的零分支不被正最短路径吞掉 | 2 | 3 |
| N07 | Star 的零分支与最短分支分别参与后续拼接 | 2 | 3 |
| N08 | Plus 的子路径长度不同，按既有 Recursive 选最短 | 1 | 2 |
| N09 | 局部最短后再反向拼接 | 4 | 3 |
| N10 | 三边条件放在局部最短选择之后 | 3 | 3 |
| N11 | 嵌套作用域与普通一步路径取 Union | 2 | 4 |
| N12 | 局部结果为空时 Optional 仍提供零分支 | 1 | 4 |
| N13 | 同一最短子表达式拼接两次，但只查询一次 | 1 | 2 |
| N14 | IN 两步 TRAIL 后接 OUT，保留平行边身份 | 2 | 3 |
| N15 | 两层有限 WALK 可直接原生展开 | 4 | 1 |

## 真实结果与修复记录

1. 首轮 session31786：通过普通 semantic Traverse 入口，**30/30 双后端执行、
   30/30 独立目标查询答案正确**，分别对应 86 次编译片段调用和 30 次目标调用。
   之后规划验收的本地比较代码因缺少可选 `ordered` 字段中断，进程 exit1，
   因此不能把整份原始记录标成成功。N01 的规划工作在异常之前尚未落盘，
   不虚构该段的完整实测计费。两服务正常停止。
2. 修复比较接口的默认无序语义，新增命中/不命中的最小本地回放。只补跑
   尚未完成的规划部分：session64470 exit0，**3/3 程序、6/6 候选答案与原
   两后端 slice 正确**，未重复上述 60 个已通过目标。
3. 复查补上原始语义的前置校验。最终 session59889 exit0，在当前源码上
   再验证 N01/N08/N13 的规划与原 slice：**3/3、6/6 与 slice 均正确**。
   14 次观测＋7 次 serving；7 次其他候选验证和 2 次旧 slice 分开记。
   最终记录的 29 个源码及 42 个旧/32 个新 fixture 哈希与当前一致。

首轮与最终版之间，变化仅涉及原生 runner、toy 比较 helper 和 scoped planner
的原始语义前置校验；路径组合与数据库查询生成代码不变。前置校验前的
30＋30 记录被保留，未冒充在最终版上全部重跑。三个原生运行的 owned 服务
均正常停止，无强杀升级；没有失败数据库动作的自动重试。

本轮发生中断与补测，首轮还有未落盘的规划工作，因此不把合并开发过程的
总时间/总成本当性能实验。新正常规划记录包含全部生成片段的观测与执行成本；
coordinator 新增显式 Cartesian/power 行数增长代价估计，仍是未校准 proxy，
可能明显高估被路径约束大量剪枝的执行，不能证明计划最优。

## 本地 gate 与边界

- 原 scoped focused session37631：155 passed / 11.32s。
- 本地比较回放 session89075：22 passed / 7.23s；最终准入回放 session51426：
  23 passed / 7.56s。包含完整链、观测/选型/执行、共享输入、原生预算及非法
  原查询不能被 WALK 候选合法化的检查。
- 最终 daily session59218 exit0：**358 passed / 24.12s**，原 18 题 demo 正常。
- 首次 broad session62508 因准入补丁主动中断：exit2，1263 passed / 3 skipped，
  不是验收通过，也不是因等待超时丢失进程。最终 broad71124 exit0：
  **3,203 passed / 38 skipped / 663.04s**，全部 24 个 harness/example 入口通过。
  最终 gate 启动后只有文档更新；所有本轮测试与原生进程均已终止。

早期本地 probe 的 RDFLib 并发 parser 错误由测试客户端加锁解决；没有改成
真实服务串行执行。旧 nested-WALK 拒绝测试已迁移到仍不受单查询原生编译支持
的嵌套非 WALK 边界；正常执行计划现在可以显式组合该类查询。

复现入口：`scripts/run_toy_development.sh`、
`scripts/run_toy_backbone_native.py --scoped --execute`（显式指定已准备的 runtime、
Java 与新的输出目录）、`scripts/run_acceptance.sh`。剩余规划可用
`--scoped --scoped-planning-only --execute` 单独验证。

原始记录目录：

持久化摘要：`experiments/artifacts/toy_backbone_t1_scoped_paths_20260911.json`。

- `/Users/anthonyche/xgap-data/t1-scoped-native-20260911/`
- `/Users/anthonyche/xgap-data/t1-scoped-planning-native-20260911/`
- `/Users/anthonyche/xgap-data/t1-scoped-planning-final-20260911/`

仍保留有限原生 128 分支/64 边预算，以及已有身份/domain 和合取条件 profile；
原生 OR/NOT 等条件尚未因此实现。此策略会额外获取未被外层条件裁剪的子路径，
以保证局部最短的语义；规模下的高效执行需要后续优化。无界原生递归、更广
typed 聚合/排序、一般源划分与流式执行仍未完成。新结果属于小图系统正确性，
不是 NL 准确率、规模性能、memory 收益或 SOTA 结论；完整 T1/T2/T3 仍未验收。
