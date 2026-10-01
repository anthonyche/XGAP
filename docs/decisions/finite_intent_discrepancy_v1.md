# 有限意图家族的 discrepancy 与 terminal certificate（v1 提案）

2026-09-16。用户明确授权“你可以提供一个理论定义”，允许先做可执行版本。
这是可替换、受限的理论提案和 opt-in 工程契约，不代表用户已认定最终论文定义，
也不替旧实验补发 epsilon 保证。

Material Passport：材料为用户关于 terminal-first、隐藏权威模拟用户、AND/OR 和
PTime 的要求，以及本仓库 compact-query / strong-planning 实现；本文件定义与证明
由本轮提出；适用对象为结构化的有限意图家族；不主张文献新颖性或开放 NL 覆盖。
证据状态：理论条件保证 + [小图实现验收](../report/intent_terminal_20260916.md)。

## 1. 数学对象与范围

冻结一个有限意图语言实例 \(\mathcal Q_0=\{Q_1,\ldots,Q_K\}\)，以及
稳定的语义角色、坐标 \(z_j(Q)\)、非负的使用预算、源快照和 compiler profile。
此处 K 是**声明家族的完整大小**，不是声称覆盖真实意图的任意 LLM top-K。
允许仅为其中小部分候选提出/生成执行方案，但证书不能遗忘其他仍可能的意图。

v1 使用固定 compact-query 骨架及非重叠 JSON 字段作为坐标：例如跳数上限、
时间边界、聚合、关系、实体约束。所有候选之间的差别必须完整落在这些坐标内；
其余固定字段是硬不变量。候选坐标向量必须不同，坐标名称、角色和权重事先冻结。
不是对任意查询图做同构/等价判定；不支持的重命名或结构变化不能悄悄进入该家族。

显式硬约束不参与“花 epsilon 换掉”的交易。对需要继续澄清但不能放宽的硬坐标
集合 H，任何候选若与仍可能的真实意图在 H 上不同，证书直接不通过。候选也不得
违背已经收到的权威回复，即使该坐标原本是软坐标。

软坐标集合 J 具有正整数权重 \(w_j\)，\(W=\sum_{j\in J}w_j\)。定义

\[
d(Q,Q')=\begin{cases}
+\infty,&\exists h\in H:z_h(Q)\ne z_h(Q'),\\
\frac{1}{W}\sum_{j\in J}w_j\mathbf1[z_j(Q)\ne z_j(Q')],&\text{otherwise}.
\end{cases}
\]

没有软坐标时，同一硬向量的距离为零。在固定硬约束分区内，这是声明意图表示上
的加权 Hamming metric；跨硬分区为扩展距离。它度量的是**声明的意图选择差异**，
不是答案集合、自然语言句子或任意查询语义的距离。两个数据上碰巧答案相同的
不同意图仍可有正距离。

首个 toy 用两个等权软维度，不根据实验胜负调整权重。常量字段不加入分母，
实现拒绝这种通过添加无变化维度“稀释”距离的做法。声明一个坐标代表一个语义
决策；权重如何反映应用损失仍须在论文中论证，而非由本公式自动证明。

## 2. 状态、权威与证书

令 \(s\) 包含公开家族、冻结源状态、预算及**已经实际收到**的权威观测。
保留集合

\[
\mathcal I(s)=\{Q\in\mathcal Q_0:\ Q\text{与全部已取得的权威回复一致}\}.
\]

模拟用户私有持有 \(Q^*\)，planner 不预读它；执行询问后，只获得选中范围的
答复。模型分数、成本估计、结构类型检查均不能删掉 \(\mathcal I(s)\) 中的可能性。

对 \(Q\in\mathcal I(s)\) 定义确定性 worst-case risk：

\[
U_s(Q)=\max_{Q'\in\mathcal I(s)}d(Q,Q').
\]

BoundedTerminal 要求 \(U_s(Q)\le\epsilon\)，同时通过真实的源映射、能力、
编译和执行预算检查。ExactTerminal 使用同一检查器，令 \(\epsilon=0\)。
在本注入式表示中，零界意味着权威信息及已声明完整家族已唯一确定意图；不是
“模型最有信心”，也不必重复询问已经由权威约束唯一推出的每一维。

**保证。** 若 (a) \(Q^*\in\mathcal Q_0\)，(b) oracle 回复真实且范围正确，
(c) 家族、metric、映射与源快照按契约冻结，则每一个实际运行前缀都有
\(Q^*\in\mathcal I(s)\)。因此在任何自适应停止时刻返回 certified Q，都有
\(d(Q,Q^*)\le U_s(Q)\le\epsilon\)。证明是集合包含关系；无需枚举未来执行结果。
观测只缩小 \(\mathcal I(s)\)，故对仍一致的固定 Q，U 单调不增。

这也是 why terminal-first 成立：每次先检查 U；已满足约束就不必再买信息。
证书通过后，按冻结的估计成本/相对排序选择及规划候选，最后只执行一次。
先便宜后选择含义的逻辑相反：成本不能决定候选是否满足语义契约。

## 3. 覆盖缺口不能用 top-K 掩盖

完整家族是必要前提。v1 的 `coverage_basis` 是可信 host 的显式实验/应用契约，
不是从模型 JSON 解析出来的“已覆盖”标记，也不是证明开放 NL 覆盖的算法。
toy 的隐藏用户只能在公开家族中选意图；完整家族及相同权限对两模式共同可见。

若只有模型 top-K，真实意图可能位于 OTHER。v1 此时返回 `unknown_coverage`，
不能使用“top-K 内的最大差异”冒充全体可能意图的界。收到家族外的权威回复，
该契约失效，保留失败与费用。生产 NL 的后续路线是先获得足够的权威范围信息，
或走已有 full-intent 模拟用户动作建立新的完整表示；本轮未完成该主入口接线。

如将来定义经过验证的 posterior，可以另外定义
\(R_s(Q)=\mathbb E[d(Q,Q^*)\mid s]\)。那是另一份期望风险契约，需要覆盖遗漏、
概率校准和自适应选择条件；不能直接用 LLM confidence 代替。Conformal Risk Control
讨论的是在其校准/交换性及损失条件下的期望风险控制，不自动提供本文每题、每前缀
的确定性上界。[原论文](https://arxiv.org/abs/2208.02814)。

### 不枚举组合的后续实现形式

定义不要求永远把所有语义组合显式列出。若有覆盖真实取值的公开/权威槽域
\(D_j(s)\)，可以使用外包盒 \(\mathcal I(s)\subseteq\prod_j D_j(s)\)。对
满足已获权威回复的候选，保守上界为

\[
\overline U_s(Q)=\frac{\sum_{j\in J}w_j\mathbf1[D_j(s)\not\subseteq\{z_j(Q)\}]}{W}.
\]

硬槽同样要求全部可能取值与 Q 一致；未知结构/OTHER 不能当成空域。该上界允许
外包盒含无效组合，只会更保守；不需要生成或执行笛卡尔积。槽域经验证覆盖真实
意图时，top-K 仅是可选输出候选，**不需要也不可以当成全部 uncertainty support**。
维护槽域后，每个候选的证书检查可为 O(m)。本轮实现的是显式有限家族的紧上界，
没有声称已实现 factorized slot-domain 入口或开放 NL 槽域覆盖算法。

## 4. PTime 与算法边界

设 K 个公开候选、m 个槽、总输入字节 B。结构一致性检查为多项式；两两距离表
成本 \(O(K^2m)\)，使用精确分数，位复杂度另由权重和输入编码长度界定。
当前实现逐候选重查support，一个状态给全部候选认证保守最坏为 \(O(K^2m)\)，
无需物理执行或catalog重建。原先较紧界需要另加support缓存，现不据此声称已实现。
v1 只有通过证书的候选才做 lowering/physical preparation；失败准备会记忆，
每个候选最多一次，最终后端执行最多一次。

当前实现的 fallback 选择“最小化最大结果分组”的单槽询问，平局按硬槽、冻结
槽序处理。只询问尚有两个以上可能值的槽。任一真实分支都会排除至少一个候选，
且不会重复槽，因此最多 \(\min(m,K-1)\) 次澄清即能唯一确定意图。
这是**终止/查询次数上界**，不是全局最优或近似比。若每个剩余真实意图都可执行、
oracle 可用且预算至少该上界，则 fallback 可得到语义可执行选择；编译/服务失败
仍是独立失败，不能据此宣称已有物理 strong policy。

还有一个有用的**相对当前fallback的信息成本保证**：若两模式共享状态、确定性的
槽选择规则、oracle与费用，且可选terminal都能编译执行，那么
\(N_\epsilon(Q^*)\le N_0(Q^*)\le\min(m,K-1)\)。原因是两者在停止前沿同一
信息分支前进，而epsilon=0的terminal也必然满足epsilon≥0；Bounded最晚在Exact
停止处停止。对于各动作非负的固定声明费用，它支付的是Exact动作序列的一个前缀，
所以声明acquisition费用也不增加。该界不是相对全局最优策略的近似比，不保证实际
墙钟时延或总成本不增加：certificate、准备及执行费用仍可能抵消少问的收益。

```text
while budget permits a state:
    check certificates in frozen estimated-rank order
    if a consistent certified candidate has a feasible compiled plan:
        execute that plan once; return
    if no information budget: return safe non-answer
    ask one varying slot chosen by minimax partition size
    retain the paid observation; intersect the possible-intent set
```

总体实现保守上界可写为 \(O(K^2m+(m+1)(K^2m+K\log K)+K C(B))\)，其中 C 为
当前有界语言的编译成本；不包含一次最终数据库查询的数据复杂度。
实现限制 2≤K≤64、1≤m≤32、单 compact query≤64KiB、物理准备≤64 次；只沿实际分支
维护状态，不生成全部 AND/OR 树。metric 表及状态证书缓存有内存界，缓存按
家族/权重/快照/epsilon/已观察状态隔离。

后续接回共享 AND/OR 搜索时，terminal contract 仍使用以上检查器；OR 选择获取
信息或执行，AND 分支包含选中动作的全部声明结果，保留 feasible strong incumbent。
固定深度 H 的显式有限树搜索是多项式（多项式次数依赖固定 H）；H 成为输入时
不能仅凭“有限深”声称 PTime。有界启发式必须分别报告状态/时间上界、incumbent
及未知 root gap。T1控制入口只实现逐槽fallback；2026-09-17新增主NL/shared-strong接线见
[T2契约](family_strong_terminal_v1.md)，T1作用域与历史定理不自动推广到T2。

## 5. 与答案、性能实验的关系

\(\epsilon=0.1\) 不是“答案错误率≤10%”。一个很小的时间/实体变化可能改变全部
结果，不能从本 metric 推出答案 F1、recall 或数值聚合误差。分别记录意图距离、
独立答案距离（如 set-Jaccard）、answer coverage、澄清数、tokens、probe/源调用、
bytes、certificate/search CPU 与总时间。拒答不是空答案，未知费用不是零。

逐槽 toy 只有 scoped clarification action，证明少问机制而非最佳信息策略。
已有系统中的 full-intent 询问不得在真实比较中被故意移除；若一问全部同样便宜，
Exact 可以一问解决，当前 toy 的少问优势可能消失。必须在相同动作/权限和真实
计价下比较，不注入虚构真人等待时间或只对 Exact 施加限制。

离线建 catalog、训练、公开家族及 metric 构建分别记录；可复用成本按 workload
摊销。本轮计量把首次距离表构建仍计入在线 certificate 时间，不凭标签免费扣除。
旧 traces 没有完整家族，仍然没有 epsilon certificate；不重写历史结果。
