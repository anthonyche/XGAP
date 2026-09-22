# XGAP 当前 Goal

最新更正：论文 Two-stage 是外部方法串接，LD 退出实验；内部两阶段变体仅留历史诊断。
按[新方法定义](decisions/ch6_external_twostage_20260922.md)推进外部准入与同部署比较，
不再运行旧主对照。已完成预选 6 题的 XGAP 自身实测：6 NL + 6 受控执行全部匹配
独立参考，见[真实结果报告](report/ch6_first_real_20260922.md)。下一步是外部组合验收、
搜索时限回退和数据移动瓶颈，以及正式工作负载/预算冻结；不是整体实验目标已完成。

2026-09-21：以论文新定义为准，完成统一的信息获取、物理规划与执行系统，
采用固定 D 步 lookahead，每次只实施选中的一个动作，观测后重规划，最后执行一个计划。
Lambda/epsilon 是验证与解释损失契约参数，撤销“两个模式必须形成优势”的开发目标。

2026-09-22 新授权：按[第六章实验计划](ch6_experiment_plan_20260922.md)、
[查询规范](query_structure_spec_20260922.md)、[交接说明](coding_agent_brief_20260922.md)
推进 inventory、结构抽取、三域开发 workload、方法对齐和 pilot 预算准备。
用户随后允许更换 D2，已接 MovieLens 小开发包，正式候选为稳定 20M；
见[数据与方法决定](decisions/ch6_dataset_and_methods_20260922.md)。
用户随后明确要求“请继续推进得到实验结果”：现推进已冻结预算的小批真实模型/后端实验，
见[首批实测协议](decisions/ch6_first_real_pilot_20260922.md)。全量矩阵仍需先完成准入和预算冻结；未恢复旧自动任务。
应用中旧三数据集 Goal 仍为 paused，不能把这次工程完成写成整体论文实验目标完成。

## 本轮交付

1. 统一入口、独立强制验证、固定深度搜索和观测后重规划。
2. 补齐截断叶的完成成本；保留可构造完成路径，预留剩余验证和执行资源，
   阻止可选探测耗尽已知可行路径；无进展动作不会因增加时间戳/收据而重新获准。
3. 有界计划池、受保护种子、单步物理变换、实际选中的统计/metadata 工具，
   以及依赖证据的估计缓存。预估与真实成本分开记录。
4. 新版批量方法/配置版本，压缩证据、独立评分、预算限制、不重复续跑。
5. tiny 原生 Neo4j/Fuseki、同事实 RDF、真实 Qwen 与保底预算拒绝验收，
   并忠实记录外部原版方法的接入失败。详见[验收报告](report/unified_prerelease_20260921.md)。

## 持续原则

- 开发用极小图、模块测试、NL→gold query→plan→target query→结果的完整切片和 failure replay。
  大数据集用于冻结后的评价，catalog 离线构建并冻结，不进 runtime。
- 模拟用户持有权威信息；按动作披露并计费，不要求真人逐题在线，也不预读隐藏真值。
- 有界语义、PTIME 在线协调工作、一个最终执行；不宣称全局最优、任意 NL 或答案误差界。
- 保留 unfavorable results；基线只做忠实接入，不改善其方法结果。
- 研究指标围绕端到端成本、答案质量/coverage、信息获取及规模；离线一次性成本单列。
- 不用当前题多计划试跑来选择；相对成本模型可用于排序，共同目标仍需声明可比工作单位。

## 尚未完成的整体目标

新版正式矩阵与预算尚未冻结。当前 D1/D2/D3 分别是 SNB-derived、MovieLens-derived、
FinBench-derived；Freebase/FedShop 不再是这次三域准备的启动前提。
原版 ARUQULA+FedUP 的模型/lookup 已接通，但所固定 FedUP 拒绝作者的 VALUES 查询，
不能声称已跑通完整 baseline。[本次准备交付](report/ch6_preparation_20260922.md)与
[roadmap](roadmap.md)分别记录已做和仍需做的工作。

[此前 Goal 全文](goal_history_20260921_before_unified.md)保留全部阶段与原始研究范围，
[旧正式结果](report/chapter7_finbench_primary_20260921.md)保留原版本，不改标签。
