# XGAP Active Goal

## 当前目标与工作时段

2026-09-15。02:00–10:00的暂停已结束；用户最新要求本轮执行结束后先验收和讨论。
因此本轮仅完成现有冻结运行及封存报告，不自动启动后续工程/实验；若没有显著优化
方案就暂停循环，等待更好的idea。总体研究Goal未完成。旧调度及应用Goal内的早期
P-S2/P-S3进度不作为自动开跑依据，以本页和[当前状态](status.md)为准。

已封存冻结提交5d82b6f的首轮FinBench strong评价：native 48题×2模式、同事实RDF
48题×6方法，每方法每题一次。发布和原始结果见[首轮报告](report/partial_strong_first_pass_20260915.md)。
新工程版本不得改写这一轮的题目、参考答案、baseline、估计器、失败或计时记录。

供验收讨论的后续候选只针对主结果暴露的具体风险，尚未授权在本轮之后自动执行：模型usage记录贯通、同源完整读取在输出字段
重命名下的安全共享、冻结统计与相对排序估计的一致接线。先小图和保存的失败回放，
再必要的真实Neo4j/Fuseki小图门；不在FinBench评价集上反复调试或按观测赢家调分数。
PERFORMANCE需要减少实际在线工作；不能只因规划预算较小就宣称端到端优势。

## 研究目标与不可变边界

构建用于真实论文实验的research prototype，不追求通用产品或无限语义。
数学对象是有限深AND/OR strong policy：OR选动作，所选AND动作的每个声明结果都要
有完整可行后续。先保留全策略可行解，再在明确输入/状态/动作/候选界限内按冻结
估计器有界改进。运行期走实际观察分支，执行一个最终联邦计划。禁止执行当前题的
多个候选后选实测赢家；无隐式retry/repair，不claim全局最优。资源上限不是质量近似界。

两模式共享骨架：EXACT要求可信查询结构及逐槽验证；PERFORMANCE可在明确授权
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
