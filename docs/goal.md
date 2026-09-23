# XGAP 当前 Goal

2026-09-23 重新连接后的当前执行边界：按
[正式物化决定](decisions/ch6_formal_materialization_20260923.md)完成三域真实材料、
模板族隔离、因子准入、F6 池与支持/预算冻结。**不启动全量；准备后先跑一个数据集。**
数据准备、数据库就绪、测试题就绪、正式结果四种状态分开记录。

本轮最新进度见[准备记录](report/ch6_materialization_progress_20260923.md)：D1/D3 两部署
真实 pilot、D1 N/u/source/scale 因子均准入；D2 两后端完整物化已封存。
下一步优先完成 D2 实际查询准入与独立 test bank 的参考计算，再补全三域发布/预算。
不得把修复提交、物化成功或准备 bank 当正式方法结果。

最新补充：混合 workload，按事前冻结的各方法支持子集统计并报告支持率，保留同子集
XGAP 配对结果。已授权直接使用 CWRU CPU/存储 + 现有外部 Qwen API，不申请 GPU。
见[远程执行决定](decisions/ch6_cwru_cpu_20260923.md)和[本轮小 gate](report/ch6_five_method_gate_20260923.md)。

**2026-09-23 当前任务：正式实验启动前准备。**按
[五方法执行合同](ch6_formal_execution_20260923.md)完成 artifact、流程、脚本和评估矩阵。
21 图各保留 XGAP、NP、SH、GR、TS；F6 成本敏感性；不补零或造曲线。本轮不启动全量。
先验证五方法 dispatch、容量和计量，再冻结三域 held-out/存储/预算。设计与代码就绪不等于全量准入。

**当前 milestone 已完成：baseline 正常产出。** ARUQULA→FedX 在固定 tiny 单源与
两源题均完成最终执行，答案评分分别保留为 0；不再优化 baseline 质量。
见[接通报告](report/ch6_baseline_admission_20260922.md)。下一步转为正式实验接线：
注册外部批量 worker、共同 RDF/同题/metadata/计量、冻结正式 manifest 与预算。
先推进 D3 SF0.1 配对实测；D1/D2 的装载与 workload 准入另行补齐，不冒称全量就绪。

以下保留本轮推进背景，以最新接通报告为准：

本轮后续已完成有界规划缓存与超时进展保留；3 个固定真数据实例、FedX 协议验收和
原版 ARUQULA→FedX 方法尝试均已封存，见[报告](report/ch6_planner_external_followup_20260922.md)。
当前 milestone 明确为 baseline 端到端产出结果；必要中间适配与管道已获用户授权。
优先接通 ARUQULA→FedX，独立报告单源/跨源的运行完成和答案评分。保留旧失败，
固定并披露结构化输出、工具语法及原生执行器兼容配置；不注入 gold 或按成绩调方法。
继续共同 RDF 工作负载、模板与
预算准备，以及合法过滤/绑定候选的成本比较；整体论文实验目标尚未完成。

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
