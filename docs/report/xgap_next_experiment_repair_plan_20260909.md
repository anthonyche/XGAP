# XGAP 下一步修复与实验计划

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: plan
- Origin Date: 2026-09-09
- Verification Status: 基于已记录结果的计划；新增实测与时间预估未验证
- Version Label: xgap_next_experiment_repair_plan_20260909

## 当前判断

已有 FinBench 物理实验获得限定范围的论文结果准入；这不等于全部
research question 已验证。GrailQA development18 是完整保留的负结果：
17/18 provider 完成，但合法候选为零。13 条存在 catalog／检索／提示词
可见性障碍；其余 5 条可达问题仍然没有合法候选。因此不能把问题全部
归因于 RAG，也不能把 catalog 构建审计通过解释为覆盖完整。

目标是尽快取得可解释的新结果，而不是继续以代码测试数代替实验效果。
保留 FinBench 与 GrailQA 两个 primary 数据集上原始 EQ1–EQ5 的全部义务。

## 修复顺序与验收

| 优先级 | 修复内容 | 通过标准 |
|---|---|---|
| P0：输出契约与运行入口 | 固定解析器；明确完整 anchors、合法 component references；在发送前检查完整 generation/repair 请求长度及服务端分词一致性 | 离线反例通过；实际请求可核验且不超预算；不靠补造 anchors、放松 grounder 或截断请求通过 |
| P1：有效候选 | 在同一 development18 上测试独立版本的输出契约，其他条件保持不变 | 分别报告全部18与原可达5条的合法候选覆盖、准确率和失败原因；若仍为零，定位新原始响应，不扩大到150 |
| P2：覆盖 | 分开修复8条 catalog 缺失、4条检索遗漏、1条提示词不可见；用 inference 可获得的知识源与预算内 packing | 同一问题集逐层覆盖可复现；无 gold 注入、无暗中扩大上下文；报告未覆盖问题，不剔除 |
| P3：通用链路 | 补 FinBench 的语义问题／ontology reference；补 GrailQA 的真实联邦执行与等价物理备选计划 | 两数据集都能经过 interpretation → validation → planning → execution → evaluation；不支持的片段显式失败 |

P0 的解析、契约草案、请求预算与独立运行入口已有本地实现；服务端逐请求
tokenization 比较是最新工程补充。它们尚无新的 CWRU 语义成功证据。
工程边界和最新验证记录见
[服务端分词修复说明](grailqa_server_tokenization_v1.md)。

## 下一次小实验：只回答“合法候选是否恢复、为什么”

- 固定同一18条、同一模型、同一检索输入、同一语义校验与评价规则。
- 显式选择新的输出契约版本；保存旧负结果，不覆盖、不重新标成成功。
- 每条最多一次 generation 和一次现有 schema repair；不自动重试失败
  外部调用。分词核对调用与模型调用分别记录，耗时计入端到端成本。
- 报告完整输出率、anchors/reference 合法率、至少一个合法候选的 query
  比例、语义匹配、调用／token／时间成本，以及完整失败分类。
- 不把服务返回成功、JSON 合法、审计成功当作语义正确。至少出现合法
  候选只说明打通接口，不说明方法优于 baseline。
- 此轮是开发诊断，不是相对历史运行的确认性因果比较。后续覆盖干预
  另设版本，避免 prompt 与检索同时改变而无法解释效果。
- 18条运行范围需单独授权；150条仍不得凭借本地测试或旧审计自动启动。

## 两数据集都要完成的比较矩阵

以下是待完整冻结的实验设计，不是已经执行的结果或新的科学决策回执。

| 原始评价问题 | FinBench 与 GrailQA 都报告 | 对照／消融设计 |
|---|---|---|
| EQ1：语义质量 | entity／predicate／path 及完整解释准确率、候选覆盖、硬约束违规、可达上限、失败类别 | 原始 ontology-relative 对比 schema-only、LLM-only；补充同一合法候选集的 confidence-top1／first-valid 对照及独立检索／输出契约消融 |
| EQ2：语义界限的作用 | ε 改变时的 precision／recall／cost、解释及答案准确率、覆盖、返回数量、语义偏离 | 严格解释与分级软语义界限；所有对照仍保留硬约束与类型安全 |
| EQ3：规划／剪枝 | explored／pruned states、规划时间、剪枝收益、质量损失 | 分别移除 semantic-dominance、cost-bound pruning，再比较同一受支持有限空间的无剪枝／穷举；评价 oracle 不进入在线选择 |
| EQ4：执行效率 | selection+serving 时间、吞吐、bytes、backend calls、资源成本；补充胜者准确率与 regret | 原始跨平台执行对比 centralized migration、pipeline-style；补充固定两种路由、family-global、family-memory、current-query profiling，同时计入 acquisition 成本 |
| EQ5：稳健性 | 原始 partial／noisy ontology mappings、heterogeneous capabilities 下的质量／覆盖／成本；补充冷 family、延迟、超时与规模变化 | 冻结映射与能力扰动以及 query／family 切分，保持硬约束；memory／acquisition 消融单列，超时不能择优重跑 |

正式比较必须共享问题、输入可见性、可用计划空间和计费口径。模型候选
质量与选择器质量分开评价；多候选 recall 不能替代 rank-1 accuracy。
按 query 聚合重复测量，报告效应量、区间、失败分母及适用的多重比较
控制。冷 family 与已见 family 分层，不能合并后宣称泛化成立。

FinBench 现有证据中 family-memory 与某些固定／family-global 基线选到
相同计划；不能据此声称 instance-specific memory 有独立贡献。新实验
应能区分这些机制，而不是只增加重复次数。数据仍须准确描述为
FinBench-derived 公共合成 benchmark，不冒称真实银行数据或官方合规分数。
新问题集须在观察比较结果前按输入属性与公开采样规则冻结，不能挑选
已经知道有利于 memory 的问题来制造优势。

## 时间与交付边界

1. **最近一轮交付**：P0 工程包和明确的18条运行范围；获得授权与服务器
   条件后，小实验产生新语义结果。单轮运行时间不包含 GPU 排队和失败修复。
2. **随后的开发闭环**：依据18条实际输出做一次可解释的覆盖干预，确认
   处理链路可用；不承诺通过某个准确率门槛，更不无限调参直到成功。
3. **正式实验交付**：补齐两数据集的缺失链路，冻结问题／baseline／消融／
   统计方案，再执行完整矩阵。150内重复使用的开发18必须披露，不能算作
   未见测试集。已有 FinBench 结果保留，新增比较独立编号。

当前不能诚实地把完整论文实验承诺为“再跑一次”或给出固定完工日期：
GrailQA 合法候选与跨数据集缺失链路仍是实质工作。应按实际 submission
deadline 倒排，先冻结必须的主结论和完整矩阵，再评估可选扩展；不能
未经作者选择删除尚未完成的 research question 或数据集。

细化的现有证据、原始问题编号和缺失单元见
[RQ × dataset 覆盖清单](research_question_dataset_coverage_v1.md)。
