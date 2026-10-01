# 3886776 部分结果后的共享入口修复

## 证据和本轮边界

用户提供的日志片段包含 78 个不同方法请求、18 个问题 ID：D3 48 条、D2 30 条。
其中 12 answered（均 EM=1）、50 intent_outside_proposed_scope、8 proposal_failed，
TS 为 2 method_error、6 harness_budget_censored（EM=null）。这是部分日志，
没有 D1 前缀和作业终态，不能当作 48 题整轮统计。

四个内部方法在同题上重复出现入口失败，优先检查共享 interpretation/scope 接线，
不是逐题改物理 planner。3886776 仍固定在 b86ada5；本轮不取消、不重提、不修改
在途 checkout，不替 TS 改答案或算法。SSH 和浏览器读取均超时，已请求一次只读
终态/归档查询；完整原始记录仍待回收。

## 已复现并修复的共性错误

1. **W4 的关系类型坐标错误依赖边数组位置。** 在公开 toy 的 zigzag 上，只重排
   边声明，提案仍为等价查询，旧 scope 却把关系选择写入另一条边；重建的八个候选
   与原候选集合没有交集。新增公开 `edge_selector`：只在原冻结类型域内定位唯一
   边，零或多个匹配都拒绝，不猜边。六种排列现在产生同一候选集合。
2. **等价表示被保守误拒。** representation identity v3 在变量角色着色前处理
   引用间 eq/ne 对称性；distinct contribution 键顺序不影响身份；v2 非聚合的
   冗余 contribution 在两端对称消除。保留常量、边方向、聚合字段、distinct、
   输出别名和顺序等实质语义。无需枚举变量排列，不扩大到任意查询等价证明。
3. **普通批次日志缺少底层阶段。** 增加已记录的 lowering/admission 错误、scope
   confirmation、源请求/转发计数、预算类别及 TS 的安全异常类型。TS 异常放在
   `method_error_type`，不冒充 observer 完整性错误；不复制模型原文、密钥或私有
   查询，不改变分数、调用预算和重试行为。

旧 scope 文件及 SHA 保留。只有显式 compact-equivalence NL 配置在新代码运行时
采用 public-edge-type-domain-v1 适配；回执记录原策略、有效策略和 hash，controlled
路径不变。新题包发布器直接生成 selector。旧实验结果绝不回填成新版本成功。

## 一次归类，避免逐题收集

`scripts/audit_ch6_nl_failures.py` 从封存 terminal/outcome/core 和固定输入读取证据，
逐份核验 SHA，一次输出失败阶段与 AST 差异路径。私有意图仅在执行结束后的离线
诊断中比较，不回馈在线方法、不输出私有值、不生成或修订答案结果。

在旧 3885860 上已完成离线审计：98 sealed 中 60 proposal、21 scope、16 answered、
1 harness。60 个旧 proposal 中 48 是身份字段表示，8 是重复变量，4 是错误节点类型；
b86ada5 已有转换可让其中 48 个通过 lowering，不等于答案正确。21 个 scope 中，
本轮身份比较可消除 1 个冗余 grain 差异；余 20 个仍有 COUNT 字段、distinct 或关系
类型差异，不能无依据声明等价。原 16 个已匹配解释保持匹配。

旧审计：`/Users/anthonyche/xgap-data/outputs/xgap-small-real-20260926-v1/nl-failure-audit-3885860-v1/audit.json`。
这不是 3886776 的根因统计。新归档到达后，用同一审计入口处理全部记录，再按根因
修正公共契约；不再为每个错误单独要求用户查 core，也不先启动另一轮整批试跑。

## 尚未解决与下一步

- 3886776 的 50 个 scope 拒绝具体哪些来自上述错误、哪些是实际模型语义偏差，
  需要原始 proposal/scope 证据。普通状态日志不足以判断。
- `covered=false` 目前没有付费 scope-repair 行动，会在 planner/probe 之前结束。
  新增 selector 不能被说成已实现开放范围修复，更不能使用隐藏 gold 作 fallback。
- TS 的预算截断已能封存并继续，属于有记录的预算结果；2 个 method_error 的实际
  异常类型仍待原始回执。不能把这两类都叫新系统 bug 或都归咎于基线质量。
- 下一轮部署前先完成整批原始失败分类和受影响契约的定点验收。只运行修复必要的
  最小真实边界；是否扩大结果采集取决于该边界，不靠反复整批 pilot 发现基础错误。
- 小样本均值、独立因子扫描、规模和并行实验的测量范围保持区分，mockup 不混入实测。

本轮共享身份、scope、worker/batch 关联和日志/预算合同的定点检查共 92 项通过；
另有离线审计入口测试。未追加全仓回归或付费试跑。公开 selector/迁移接线经过
独立只读复核。修复、旧记录 replay 和审计均为零模型、零后端调用。整体 Goal 未完成。
