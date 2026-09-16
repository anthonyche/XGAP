# XGAP Active Goal

## 当前目标与工作时段

2026-09-16，最新授权：**继续优化，并由工程方提出可执行 discrepancy 定义**。
M0/M1小图与首轮机会分析已完成；T1新增有限意图家族的最坏差异证书及terminal-first
小图入口，见[定义/证明/界限](decisions/finite_intent_discrepancy_v1.md)和
[T1验收](report/intent_terminal_20260916.md)。这仍是可替换提案，未接管主NL/AND-OR入口。
本轮允许必要工程修改、定向测试和对应真实 tiny 接口验收；不启动 M2–M4、大数据集、
baseline 调优、全量回归或自动唤醒。实际证据见[验收报告](report/simulated_user_memory_20260916.md)。
总体研究 Goal 尚未完成。

整体路线遵循[新阶段计划](research_next_stage_plan_20260916.md)：先接入可查询的权威
模拟用户，并以小图修复多跳执行与计量风险；建立作者原查询上的FedShop/FedUP/FedX共同支持范围；冻结更有信息量
的FinBench NL评价集；分别交付固定查询执行比较与真实NL端到端结果。模式理论结合用户
进展与本轮授权提出的受限定义推进，不预设Performance必胜，不以大批消融替代理论机制。

EXACT无人值守的正确含义：现实用户不逐题参与，但必须提供持有权威意图、可查询的
模拟用户。需要澄清时向它询问并继续；不能因为现实用户没有回答就返回失败。
模拟用户可以私有持有gold语义/意图标注，通过有范围、有记录的信息动作回答；planner
不直接读取隐藏意图或最终结果。见[模拟用户契约](decisions/simulated_user_authority_v1.md)。
该模块第一版已接入并通过真实小图；有限家族terminal已另行接通，主NL的按需信息选择待接线。

首版12题/72方法观测已封存评分，服务已关闭，进入验收讨论；不自动扩量或调参。
Native两模式均7/12匹配，RDF 8/12与7/12（后者含整批磁盘预算截断）；每组4道多跳
内存失败，11题参考为空。下一轮候选优先小图上的中间结果控制与非空评价覆盖，
不得将模式差别或baseline失败包装成优势。见[本轮报告](report/nl_strong_first_pass_20260916.md)。

历史NL-only首版已在极小图检查新边界和真实模型/双后端链，再冻结12题（既有三家族各4题）的
首版评价：native两模式，同事实RDF加FedX/FedUP。只提供NL和通用schema，输入不含
每题gold结构、源分配或答案。所有失败如实计入；不在评价题上反复修补重跑。
方法、预算、输入、评分范围见[本次契约](decisions/nl_conditional_strong_v1.md)。

旧NL-only profile的查询结构由模型提出，strong保证明确限定于该结构；这不是用户意图已获验证。
EXACT仍保持声明hole的权威门，PERFORMANCE显式记录预测。首版K=1共同前端只负责
取得可信的端到端观测，不声称已验证信息获取Pareto收益、epsilon保证或SOTA优势。

保留5d82b6f的384条历史观测及[原报告](report/partial_strong_first_pass_20260915.md)；
不能把此前可信模板结果重新命名为本轮NL结果。catalog、估计器、baseline和数据不重建。

## 最新Performance验收方向

首轮[Exact prefix机会分析](report/terminal_opportunity_20260916.md)已完成：旧15条完整NL-only trace无澄清，新交互trace有3个prefix；epsilon认证保持未知。暂不大改系统。成功可以是
减少clarification、LLM/token、metadata/source probes、远程调用/数据移动或总成本，
以及Exact因预算不足safe non-answer时提高answer coverage；不要求backend execution
一定不同。主结果应为cost–discrepancy–coverage frontier，而非单一速度比。

候选/历史cache/source snapshot和oracle权限必须相同。逐状态先检查ExactTerminal或
BoundedTerminal(epsilon)，通过certificate后才生成必要物理计划；否则选择一个信息动作。
明确区分required_for_execution、required_for_exactness、optional_for_costing、proposal_only。
不能预读oracle、把模型置信度当authority、把便宜程度当用户意图、将全部最终执行时间
计成可避免成本。没有可执行certificate时eligible和root gap保留未知。
若完成合理terminal-first/lazy实现后仍没有非平凡frontier，Performance降为extension，
不调参制造优势。当前固定流程只是M0接线验收，不是Performance机制验收。

## 研究目标与不可变边界

构建用于真实论文实验的research prototype，不追求通用产品或无限语义。
数学对象是有限深AND/OR strong policy：OR选动作，所选AND动作的每个声明结果都要
有完整可行后续。先保留全策略可行解，再在明确输入/状态/动作/候选界限内按冻结
估计器有界改进。运行期走实际观察分支，执行一个最终联邦计划。禁止执行当前题的
多个候选后选实测赢家；无隐式retry/repair，不claim全局最优。资源上限不是质量近似界。

可信模板API中EXACT要求可信结构及逐槽验证；新NL入口对模型结构作条件执行而非权威背书。
PERFORMANCE可在明确授权
范围使用未验证绑定。硬约束和已验证绑定保持。本轮d采用冻结语义坐标上的加权差异，
证书取所有仍可能真实意图的最大值；没有完整覆盖依据时仍未知。提案不提供答案误差
或任意NL正确性保证。相对快慢预测可以作为估计器，
不要求严格回归时间；未知费用保持null，跨数据/后端未校准必须明示。

catalog、索引、统计、训练属于离线构建并冻结的一次性成本，与在线信息、模型、规划、
源查询分别计量。报告可按查询量摊销，但不能直接扣除没有单独测量的记录开销。

## 验收与实验策略

开发使用极小toy，分别维护Interpretation与deterministic planning测试链，以及完整
vertical slice。每题有NL、gold semantic/path query、预期logical/native plan与独立结果。
只做新风险的模块检查、failure replay与必要真实边界门，不重复已成功门增加样本计数。
GrailQA catalog完全离线；GrailQA-mini用于后续集成，全量大集只用于真实评价。

首版FinBench native与同事实RDF观察已完成。下一次恢复优先执行稳定性与有界FedShop
作者原查询对照，同时准备更好的NL评价覆盖；不以反复修补当前FinBench基线失败作前提。
GrailQA/KBQA-R1依完整KB及作者artifact后置。保留16–20图的RQ/X/Y结构：efficiency、effectiveness、
scalability、Pareto与最后的ablation。内部变体不能替代外部SOTA；总体图用同权限外部
方法同图呈现。明确共同支持范围，不把不支持语义、预算截断或失败耗时当成提速证据。

baseline只忠实适配到能运行，绝不优化算法、语义、答案或按结果调参。全体分母、空与
非空答案、错误、未知、censoring、原版本及一次性成本全部保留。既有评价曝光照实声明。
原定一周形成真实论文结果的目标不变，以实际验收为准，不虚报系统或实验已完成。

远端3804210保持用户更新，不自行查询/取消/重提；外部LLM已可用，不等GPU。
仅凭据、VPN/服务器操作、外部artifact或实质研究方向决策请求用户介入。

## 权威入口与历史

[下一阶段计划](research_next_stage_plan_20260916.md) · [算法规划](practical_planning_20260914.md)
· [技术决策索引](decisions.md) · [路线](roadmap.md)
· [系统与实验契约](research_contract_audit_20260915.md)。详细过程写独立report，不叠加旧的
“当前/下一步”。[历史快照](goal_history_20260915.md)与[凌晨报告](report/xgap_progress_20260915_0200.md)
仅作溯源，不作为当前执行指令。
