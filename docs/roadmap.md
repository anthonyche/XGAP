# XGAP 下一步

2026-09-21，本轮已到“全量实验之前”的停止点。统一控制器、动作空间、原生/RDF/模型
接口、批量证据与第六章实现说明已交付；[验收与例外](report/unified_prerelease_20260921.md)。
不自动启动正式矩阵，不恢复历史 campaign/自动化。

新版正式发布之前按以下顺序推进：

1. 以 unified XGAP 与 sequential interpretation→physical 为主比较，更新第七章映射。
   Lambda/epsilon、D、信息价格、估计器和计划池是因素；不要把旧两模式图改名作为新结果。
   [发布前检查清单](decisions/unified_experiment_release_checklist_20260921.md)列出必需冻结项。
2. 固定数据快照、共享初始状态、题目/结构/取样框、参考结果及轨道。原先批准的均匀/活跃
   双框分别报告；不能根据空答案、耗时或方法胜负换题。NL 与受控轨道分开。
3. 完成外部原版方法接入中剩余的模型可用性/调用兼容诊断；不更改作者 prompt、搜索、
   解码或结果。最新超时如实保留，不做无差别自动重试；外部方法没到数据库不算比较结果。
4. 对拟纳入的新数据映射、实际分片和外部方法，仅补一个必要 tiny 边界门；
   Freebase/FedShop 尚未准入的部分不能靠已有 FinBench tiny 成功代替。
5. 冻结 clean commit、方法配置、显式成本/概率模型、所有预算及失败/截断处理。
   随后才可发布新 manifest；已尝试单元不得覆盖或自动补跑。

不再扩展的工程范围：任意自然语言、无限路径、全部 join order、通用能力发现、
完整推理规则引擎、给所有资源制造“已证明”的上界。需要这些能力的题目标为不支持。

需要验证的研究假设仍是：联合决策是否在适当信息成本和不确定性下减少端到端代价，
同时保持声明的验证/解释损失契约与答案覆盖。结果也可能显示顺序方法足够好；保留该结论。

[此前 roadmap](roadmap_history_20260921_before_unified.md)仅用于溯源。

Transport diagnosis update: the old observer bypassed the system HTTP proxy,
while the working compact client used it. Explicit proxy support now preserves
original request bytes; a new tiny admission is needed. The old timeout remains
harness/network evidence, not an intrinsic method performance result.
