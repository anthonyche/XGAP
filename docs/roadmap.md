# XGAP Current Roadmap

T3最新授权（2026-09-17）：用户批准从toy机制门转到冻结的SF0.1策略价值评价。
[机器可读协议](../experiments/protocols/family_policy_study_v1.json)固定16题、两档epsilon、
两个简单对照、平衡顺序与少量预定重复。先封存第一次结果，再讨论改进，不在运行中调参。

2026-09-17：T2按用户最新授权完成有限家族certificate→主NL→共享AND/OR→共同worker
接线，并提供双方相同的full-intent/局部询问。先验收[小图机制与原生接口](report/strong_intent_20260917.md)，
再讨论更有信息量的workload，不启动大数据、扫参或baseline优化。
后续实质缺口：开放NL的权威覆盖范围获取；LLM/probe的按需动作；factorized support；
经冻结估计器联合比较acquisition与execution。不能把当前公开家族profile称为上述全部完成。
现行[T2策略/复杂度/边界](decisions/family_strong_terminal_v1.md)优先于下方历史待办。

2026-09-16历史：用户授权提出d；有限家族最坏差异证书和terminal-first小图门已完成，
见[契约](decisions/finite_intent_discrepancy_v1.md)、[结果](report/intent_terminal_20260916.md)。
下一步先把closed-family范围获取、full-intent/逐槽动作接回共享NL/AND-OR入口，
再对同权限trace做机会分析；不要直接把逐槽toy的2→1次当作总体优势。
保留未知覆盖、安全拒答、证书费用与答案差异，不进入大规模参数扫测。

2026-09-16：M0模拟用户第一版与M1小图内存修复已通过，见
[验收报告](report/simulated_user_memory_20260916.md)。整体研究目标未完成。

[首轮机会分析](report/terminal_opportunity_20260916.md)：仅做只读重放，0新模型/后端/oracle调用；证书缺失时不产生提前认证或收益结论。

## 当前顺序：先机会分析，再决定搜索器改动

1. 对已有完整Exact traces逐前缀重建公开状态，检查可用terminal contract。
2. 将可认证的可避免成本与乐观上限、未知项分开，保留一次必要最终规划/执行。
3. 有非平凡机会才推进统一terminal-first、lazy候选/物理计划生成。无可执行epsilon
   certificate时不能伪造eligible、root gap或coverage收益。
4. M2–M4不自动扩量；baseline算法和历史结果保持原样。

最新授权与顺序见[Goal](goal.md)及[下一阶段详细计划](research_next_stage_plan_20260916.md)。
现行实现界限仍见[NL契约](decisions/nl_conditional_strong_v1.md)。
结果见[首版NL报告](report/nl_strong_first_pass_20260916.md)：多跳执行内存、非空题覆盖、
累计日志预算隔离是下一轮优先候选；不把RDF的8/12与7/12差别解释成精度机制。

## 已通的有界骨架

- P-S1：有限深AND/OR strong policy，先保留完整可行策略，再做有界估计改进。
- P-S2：冻结catalog、可选LLM、按需绑定权威、普通profile/record入口与真实双后端链。
- P-S3：协调器/首跳/逐跳候选，完整读取共享、必要过滤、准备和预算优化。
- 共同研究入口：独立study、固定信息外部前端、监督、observer、评分与不可覆写journal。

具体实现与证据见[当前状态](status.md)及[首轮报告](report/partial_strong_first_pass_20260915.md)。
“已实现”不等于任意语义已验证，也不等于有模式优势或scalability结论。

## 下一次明确恢复后的顺序（均未执行）

|阶段|工作|进入下一步的证据|
|---|---|---|
|M0 权威模拟用户|从gold意图准备私有状态，接入可计量的澄清/确认工具，现实用户不逐题参与|小图上实际发生问询与权威回复，更新意图后形成计划并返回正确答案；不直接预填gold|
|M1 执行稳定性|极小图诊断多跳中间结果；最小等价限制传播/读取优化；隔离累计日志容量|新增语义例正确、目标例工作量降低、相关vertical slice通过；不只看偶然耗时|
|M2 作者查询外部对照|复用FedShop源码/12模板清单，验证FedX/FedUP作者路线和XGAP受限映射|至少有非平凡多源连接的共同正确完成；全模板coverage保留，原算法不变|
|M3 NL评价覆盖|建议新24题、三家族各8，预定非空/空比例与选择率；固定独立答案与曝光|运行前manifest和评分契约冻结；旧12题不充作新测试集|
|M4 首批有效比较|固定查询执行轨与真实NL轨分开发布；先正确性/效率，再规模，消融最后|同输入权限、同资源、全失败分母和可复核成本；不拿失败时间作提速分母|
|T 用户理论|用户推进d/risk与模式机制，随后接入自动acquisition与有限机制试验|明确可自动执行的证据、终止/近似界、PTime与certificate成本|

最新纠正见[权威模拟用户](decisions/simulated_user_authority_v1.md)。M0不等待用户的新
d/risk理论；“无人值守”意味着用模拟用户替代现实人类响应，不意味着取消澄清能力。
M2静态准备与M3采样设计可在恢复后穿插，计时服务运行保持串行。固定查询比较无需
等待NL manifest或新模式理论；各轨只受对应验收门约束。T不阻塞无风险界主张的工程。

FedShop目前只有固定源码/静态清单，未运行或生成数据。q09为最小接入候选，q12/q01
用于检查非平凡范围；不能以仅跑通q09称完整benchmark。2/4/8源为FedShop-derived，
官方miniature为20/40源；具体数据与预算在恢复后的release前冻结。

已有别名共享、RDF统计、排序特征和usage修复候选仅按M1根因需要选用，不自动开启
全部工程支线或重训。KBQA-R1/完整KB条件轨保留后置。具体RQ、X/Y、停止条件和
材料指针以[详细计划](research_next_stage_plan_20260916.md)为准。

## 排除的工作

不建设无限语义的通用产品；不把GrailQA当开发环境；不自动重提远端作业；不优化baseline
结果；不重复无新风险的回归或用评价赢家调整估计分数。

[此前路线快照](roadmap_history_20260915.md)保留溯源，其旧调度与“下一步”不生效。
