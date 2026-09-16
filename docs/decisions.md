# XGAP Decision Index

2026-09-16。先读当前profile及本次受影响的专题，历史用于核实旧语义/API或实验版本，
不执行其中过期的“下一步”。[当前Goal](goal.md)、[状态](status.md)、[研究审计](research_contract_audit_20260915.md)。

最新接入：[NL条件strong首版](decisions/nl_conditional_strong_v1.md)，用户已恢复执行。

## 当前用户批准的研究契约

- [Practical strong planning](decisions/practical_strong_planning_v1.md)：有限深AND/OR
  strong policy；先可行后有界估计改进；EXACT验证/PERFORMANCE授权预测；d待用户定义。
- [Ptime规划契约](decisions/planning_ptime_contract_v1.md)：输入/编译扩展/候选构造的
  多项式前提；模型特殊情形与一般启发式分开，不把budget当近似比。
- [Baseline忠实原则](decisions/baseline_fidelity_v1.md)：不优化算法、语义、答案或按结果调参。
- [信息顺序与成本分开](decisions/acquisition_order_v1.md)：search_priority是启发式顺序；
  estimated_ms未知时保持null，不为了让LLM执行而伪造高澄清费用。

## 新strong实现专题

|涉及的改动|先读的契约|
|---|---|
|模式/profile/记录发布|[practical profile](decisions/practical_profile_v1.md)|
|请求内依赖admission|[preparation](decisions/practical_preparation_v1.md)|
|逐跳传播候选|[progressive binding](decisions/progressive_binding_v1.md)|
|完整源查询共享|[shared native reads](decisions/shared_native_reads_v1.md)|
|必要源string/bool过滤|[source prefilters](decisions/source_row_prefilters_v1.md)|
|可选构造/打分的软时间预算|[cooperative budget](decisions/cooperative_planning_budget_v1.md)|
|共同worker与trusted_template范围|[worker](decisions/practical_worker_v1.md)、[native gate](decisions/practical_worker_native_v1.md)|
|小型答案/计量交付|[outcome](decisions/practical_outcome_v1.md)|
|较大源响应回放|[capture size](decisions/practical_capture_size_v1.md)|
|逐题配置、单组调度与续跑|[study](decisions/practical_study_v1.md)|
|完整可信FinBench语义输入与在线源路由|[resolved inputs](decisions/resolved_strong_inputs_v1.md)|
|部分绑定共同前端、外部组合与v2 study|[fixed information frontend](decisions/fixed_information_frontend_v1.md)|
|FinBench关系槽输入与配置候选发布|[partial inputs](decisions/partial_strong_inputs_v1.md)|
|EXACT不推进证据的动作剪枝|[evidence-progress pruning](decisions/exact_information_pruning_v1.md)|
|真实信息费用、strong专用估计排序|[cost basis](decisions/practical_information_cost_basis_v1.md)、[排序修订](decisions/acquisition_order_v1.md)|
|全策略先可行、再延迟优化terminal|[global strong seed](decisions/global_strong_seed_v1.md)|
|新strong首轮48题配置发布与真实评价|[campaign release](decisions/practical_campaign_release_v1.md)、[384次结果验收](report/partial_strong_first_pass_20260915.md)|
|为何不强制新候选胜出|[预定成本诊断](decisions/practical_cost_diagnostic_v1.md)|

## 共享语义与旧接口仍需保留

修改共享语义必须读[算子语义](operator_semantics.md)及对应局部决策，不以新模式重新
定义路径代数或绑定。旧[one-shot模式](decisions/one_shot_modes_v1.md)、
[金融population](decisions/finbench_one_shot_population_v1.md)、
[贡献粒度](decisions/compact_contribution_v2.md)、
[时间值](decisions/financial_timestamp_v2.md)、
[原生source准备](decisions/native_store_preparation_v1.md)、
[共同观测](decisions/campaign_observation_v1.md)与各自历史记录保持其版本含义。
旧关系截断不自动进入新strong profile；输出不得混用complete与approximate语义。

## 历史登记表

[逐字保留的全部历史决策](decisions_history_20260915.md)包括此前D系列、M系列和报告
更新。当前索引不删除其技术规定；触及旧模块时定位相应条目和独立decision文档。
与后续用户批准的新契约冲突的历史下一步由新契约覆盖，不自动触发旧大图或回归任务。
[历史文件hash索引](../experiments/artifacts/harness_document_history_20260915.json)。
