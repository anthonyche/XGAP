# XGAP 下一步

2026-09-22 以新的[实验计划](ch6_experiment_plan_20260922.md)为准。当前完成的是
[首次准备交付](report/ch6_preparation_20260922.md)，尚未发布可执行的全量 manifest。
不启动旧 Exact/Performance campaign 或自动任务。

1. Workload 继续准入：LC-QuAD 已有 typed AST、参数实例化与拒收证据；将明确支持的
   实例化结构接到 compact lowering。当前三域 29 个开发实例来自 authored 领域模板，
   不冒称自动转换了 LC-QuAD。核对 FinBench v0.1.0 TSR1/TCR1/TCR4/TCR12 原 card，
   明确保留/修改的时间、边贡献、截断与输出合同。
2. 扩充真实模板覆盖：当前每域仅 6–9 个规范化开发族，距离每 W 层 10 族目标仍有缺口。
   不把实体换值计为新模板；开发族全部保留在开发 split。N/u 的每个扫描水平独立检查
   真实合法域，拒收不可匹配的 cohort。修订 NL 固定条件与独立意图权威确认后才能称 NL pilot。
3. D1/D2 的原生 mapping/materialization，以及每模板真实 metadata/probe 目标和两个语义等价
   物理备选。D2 当前 MovieLens-derived；稳定 20M 是正式候选，Wikidata 为待核验扩展，
   不是已经存在的数据。实际后端 gate 须单独确认执行预算；保留小图优先。
4. Two-stage 改为实际外部方法串接；LD 退出，内部两阶段仅保留已封存诊断。
   核验 ARUQULA+FedUP 的 VALUES 兼容瓶颈及独立替代组合准入；同 RDF 部署公平比较。
   私有 gold 只进模拟用户/evaluator。统一实测成本、缓存、方法顺序、时限与资源计量。
5. 基于首批真实 XGAP 结果和外部原版准入重新冻结正式预算；旧 864-call 提案失效。
   原版外部前端可能多次模型/源调用，不能沿用每题一次模型的乘数。
6. 新 manifest 一次发布，复用图所需记录；后做规模与离线固定 Q 的 F6。N>64 尚未准入。
   原版外部方法仅按支持表纳入同 RDF 部署，不能把内部对照改名填补 SOTA。

首批真实执行已由用户“请继续推进得到实验结果”授权。方法更正立即作用于未开始的
cell，不修改既有证据。见[方法更正与停止记录](decisions/ch6_external_twostage_20260922.md)。
