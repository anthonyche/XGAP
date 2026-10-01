# Terminal机会分析：第一轮只读前缀审计

2026-09-16。先完成[模拟用户与内存修复](simulated_user_memory_20260916.md)，再按用户
要求分析现有Exact记录；本轮没有重构搜索器，没有新增模型、oracle或数据库调用。

## 成功标准

Performance的成功可以表现为：减少澄清、LLM/token、metadata/source probes、远程
调用、数据移动或端到端成本；也可以在Exact预算不足而safe non-answer时提高答案覆盖。
后端执行相同不影响信息获取收益成立。质量必须满足声明的discrepancy契约，便宜程度
不能替代用户含义。主要评价应展示cost–discrepancy–coverage frontier。

## 分析范围与前缀隔离

读取旧NL-only首版24条Exact观测中的15条完整trace，以及新 `USER-PATH-01` 完整
Exact交互trace。旧批次其余9条失败继续保留，不把它们当完整前缀时间线。
384条可信模板结果的起点与NL不同，本轮不混入该分母，也没有宣称已分析全部历史轨道。

新trace重建模型提议后、取得完整查询陈述后、取得起点身份后的三个状态。terminal
评估接口只收到当前状态的拷贝：公开提议、已收到陈述、已收到实体绑定和此前观察。
不会传入后续回复、私有oracle文件、参考答案或实测最优计划。后续记录只用于离线
计算剩余费用；那是审计者能看见的账本，不是运行策略可预读的信息。

当前未提供可执行的epsilon/discrepancy certificate，因此所有bounded eligibility为
unknown；不把unknown计成false，也不声称发现了epsilon-certified最早终止点。
最终前缀已有完整意图权威，且原run实际形成了strong计划；这与提前epsilon认证分开。

## 实际观察

旧15条完整NL-only Exact traces每题只有1次前置模型调用，均无澄清及probe动作。
它们不能用于证明“Performance少问”的收益；初始没有候选时，不能自动把首次模型
提议的费用算成可避免。未执行的其他信息策略也没有费用观测。

新trace的公开模型提议已被语法/编译入口admit、没有显式hole；这只说明结构完整，
并不构成正确意图证据。模拟用户的陈述使用实体别名，模型则使用业务ID过滤，变量
名也不同；`corrected`标签是结构差异，不等于答案一定错误。没有执行第二个候选来
事后选择赢家，也没有据此猜测empirical discrepancy。

|新trace前缀|已获得权威信息|尚余澄清|尚余已测oracle处理时间|提前epsilon认证|
|---|---|---:|---:|---|
|模型提议后|无用户意图确认|2|0.930ms|unknown|
|完整查询陈述后|结构/过滤/路径等；起点身份待确认|1|0.383ms|unknown|
|实体身份后|所需意图已确认|0|0ms|未配置epsilon证书；原Exact终点可行|

前两个是**待检查的停止机会**，不是已经认证的停止位置。即便乐观地跳过全部后续
oracle动作，已计量部分也只省2次本地询问、0.930ms、0模型调用、0token、0远程probe。
这是该费用分量的上限，**不是完整交互E2E节省的上限**：逐观察持久化等开销尚未
单独测量，不能丢掉未知成本。初始模型已付1次、2678token、约3.604s。

随后129.885ms规划、1.261s执行和12次源调用不是自动可避免成本。任何被批准提前
执行的candidate仍需形成可执行物理计划并执行；若语义不同，需先通过certificate，
再比较各自预估/实测成本。不能把Exact整段尾部5秒计成Performance收益。

预算覆盖也有可检查位置：现流程需要2次用户动作，预算1次时定向测试已观察到安全
不执行。若前面某个完整candidate日后获epsilon认证，可能提高该预算下的coverage；
目前缺少该认证，`coverage_gain`保持unknown，不能将潜在收益写成已测结果。

## 对实现瓶颈的校正

现有 `strong_planning.solve` 确实先询问 `domain.terminals(state)` 再展开actions，
`PracticalSemanticDomain.terminals`也先产出一个可行seed，再按需产生改进方案。
所以不能笼统说整个底层都是“枚举全部计划后按mode过滤”。

不过新NL交互入口先运行固定full-intent流程，再进入strong domain，导致两种模式
都已支付相同信息费用；K=1也没有多interpretation的lazy选择机会。root取得terminal
后还会进入有界refinement/动作搜索，并不自动按新的终止契约立即执行。更关键的是
没有可执行的BoundedTerminal(epsilon)。这些才是后续应调整的具体接口。

因此目前证据不支持立即重写搜索器。先复用现有state/action/backup/compiler/runtime，
将NL候选及信息动作纳入共同state，明确terminal检查与物理计划生成分界。新契约所需
状态应包含已收到证据、hard constraints、预算/成本和证书身份；返回eligible、ineligible
或unknown及其根据。未知root gap、certificate耗时和差异均保持null。

|动作类别|当前对应例子|终止/跳过规则|
|---|---|---|
|required_for_execution|源覆盖/映射、能力和可执行完整查询|两种contract都必须满足|
|required_for_exactness|完整意图与身份权威确认|Exact需要；Performance只能在certificate下跳过|
|optional_for_costing|额外统计/profile探测|需要可测信息价值；当前trace没有此动作|
|proposal_only|LLM、ontology、catalog候选|不能验证意图；当前首次LLM先产生候选，不自动算可避免|

## 下一步与停止门

1. 保留这份无调用prefix replay，接上用户提供的可执行certificate，再重放相同前缀。
   要验证其只依赖当时可见state，不能由完整gold评分回填在线认证。
2. 若发现非平凡certified机会，再将terminal-first移到固定获取信息流程之前，lazy
   生成通过hard constraints/certificate的候选之物理计划，复用缓存与现有strong搜索。
   两模式使用相同s0、candidate set、cache、snapshot和oracle权限。
3. 若当前小图仍没有机会，先改用包含真实多轮信息获取或预算覆盖差异的有界开发例；
   这是workload诊断，不是按方法输赢改评价题或给Exact注入虚假延迟。
4. 模式实验统一记录epsilon、eligibility、acquisition/LLM/token/probes、search与certificate
   时间、expanded states、execution/bytes、总成本、empirical discrepancy、coverage和root gap。
   有理论可避免收益而实现没有才重构；完成合理实现仍无非平凡frontier则将Performance
   降为extension。baseline不优化、不增加无意义消融。

可复用实现：`src/xgap/experiments/terminal_opportunity.py`，入口
`scripts/audit_terminal_opportunity.py`。3个定向测试验证prefix不泄露未来、成本归因及
过期/不完整trace拒绝，不重复先前工程测试计数。

证据：[审计摘要](/Users/anthonyche/xgap-data/terminal-opportunity-20260916-v1/summary.json)、
[三个prefix及旧15条trace身份](/Users/anthonyche/xgap-data/terminal-opportunity-20260916-v1/prefix-replay.json)。
`earliest_certified_prefix`、empirical discrepancy、coverage gain和root gap均为null，
明确表示当前契约/观测不足，绝不等同于没有潜在收益。
