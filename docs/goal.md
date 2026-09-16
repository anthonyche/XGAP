# XGAP Active Goal

## 当前目标与工作时段

2026-09-16。用户已明确恢复工程与实验，要求先在SF0.1得到可评价的真实结果。
当前里程碑是自然语言单次入口接通当前strong planner、真实Neo4j/Fuseki执行、独立评分。
不等待PERFORMANCE调优，也不等待下一版d/risk理论。此前验收暂停已被本次授权替代。
EXACT工程与实验必须无人值守：不能要求用户逐题回答或验证；使用有界自动证据，
不足时记录未解决/失败，不能读gold或使用逐题权威答案夹具来补齐。
应用Goal的存储暂停状态不代表本轮用户要求暂停；总体研究Goal尚未完成。

先在极小图检查新边界和一次真实模型/双后端链，再冻结12题（既有三家族各4题）的
首版评价：native两模式，同事实RDF加FedX/FedUP。只提供NL和通用schema，输入不含
每题gold结构、源分配或答案。所有失败如实计入；不在评价题上反复修补重跑。
方法、预算、输入、评分范围见[本次契约](decisions/nl_conditional_strong_v1.md)。

查询结构由模型提出，strong保证明确限定于该结构；这不是用户意图已获验证。
EXACT仍保持声明hole的权威门，PERFORMANCE显式记录预测。首版K=1共同前端只负责
取得可信的端到端观测，不声称已验证信息获取Pareto收益、epsilon保证或SOTA优势。

保留5d82b6f的384条历史观测及[原报告](report/partial_strong_first_pass_20260915.md)；
不能把此前可信模板结果重新命名为本轮NL结果。catalog、估计器、baseline和数据不重建。

## 研究目标与不可变边界

构建用于真实论文实验的research prototype，不追求通用产品或无限语义。
数学对象是有限深AND/OR strong policy：OR选动作，所选AND动作的每个声明结果都要
有完整可行后续。先保留全策略可行解，再在明确输入/状态/动作/候选界限内按冻结
估计器有界改进。运行期走实际观察分支，执行一个最终联邦计划。禁止执行当前题的
多个候选后选实测赢家；无隐式retry/repair，不claim全局最优。资源上限不是质量近似界。

可信模板API中EXACT要求可信结构及逐槽验证；新NL入口对模型结构作条件执行而非权威背书。
PERFORMANCE可在明确授权
范围使用未验证绑定。硬约束和已验证绑定保持。d(Q_tilde,Q_star)由用户下一理论阶段
定义；不自造epsilon、答案误差或任意NL正确性保证。相对快慢预测可以作为估计器，
不要求严格回归时间；未知费用保持null，跨数据/后端未校准必须明示。

catalog、索引、统计、训练属于离线构建并冻结的一次性成本，与在线信息、模型、规划、
源查询分别计量。报告可按查询量摊销，但不能直接扣除没有单独测量的记录开销。

## 验收与实验策略

开发使用极小toy，分别维护Interpretation与deterministic planning测试链，以及完整
vertical slice。每题有NL、gold semantic/path query、预期logical/native plan与独立结果。
只做新风险的模块检查、failure replay与必要真实边界门，不重复已成功门增加样本计数。
GrailQA catalog完全离线；GrailQA-mini用于后续集成，全量大集只用于真实评价。

按批准顺序推进FinBench native与同事实RDF FedUP/FedX，再bounded FedShop；GrailQA/
KBQA-R1依完整KB及作者artifact后置。保留16–20图的RQ/X/Y结构：efficiency、effectiveness、
scalability、Pareto与最后的ablation。内部变体不能替代外部SOTA；总体图用同权限外部
方法同图呈现。明确共同支持范围，不把不支持语义、预算截断或失败耗时当成提速证据。

baseline只忠实适配到能运行，绝不优化算法、语义、答案或按结果调参。全体分母、空与
非空答案、错误、未知、censoring、原版本及一次性成本全部保留。既有评价曝光照实声明。
原定一周形成真实论文结果的目标不变，以实际验收为准，不虚报系统或实验已完成。

远端3804210保持用户更新，不自行查询/取消/重提；外部LLM已可用，不等GPU。
仅凭据、VPN/服务器操作、外部artifact或实质研究方向决策请求用户介入。

## 权威入口与历史

[当前规划](practical_planning_20260914.md) · [技术决策索引](decisions.md) · [路线](roadmap.md)
· [系统与实验契约](research_contract_audit_20260915.md)。详细过程写独立report，不叠加旧的
“当前/下一步”。[历史快照](goal_history_20260915.md)与[凌晨报告](report/xgap_progress_20260915_0200.md)
仅作溯源，不作为当前执行指令。
