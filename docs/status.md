# XGAP Current Status

2026-09-17 T3进行中：两个简单策略（完整询问、固定槽序+同证书）已接入相同strong
检查与worker。独立CSV参考和新小图对照检查已通过；即将冻结16个新SF0.1交互问题。
研究问题是搜索器是否比简单规则有价值，不预设Performance胜出。见[T3协议](decisions/family_policy_study_v1.md)。

2026-09-17最新：**T2证书已接入主NL API/共同worker/共享AND-OR strong搜索。**
新 `xgap-nl-family-*` profile有相同full/scoped动作和预算，terminal-first、按需编译与缓存；
Exact无需真人在线。已知8节点/5意图上，Exact一问/5次编译/1次执行得到4行；
Performance ε=1/4零问/1次编译得到相同4行，ε=1/2零问得到3行、源适配器调用14→9。
真实模型＋Neo4j/Fuseki共同worker门也通过：两模式各1模型/1最终执行，4行与3行，
源调用14→9，响应正文17,872→7,582bytes；全部托管服务关闭。
这是公开有限家族机制结果，不是开放NL或统计提速。原生worker门见
[本轮报告](report/strong_intent_20260917.md)，算法/输入界见[T2契约](decisions/family_strong_terminal_v1.md)。

2026-09-16历史：**T1有限意图证书与terminal-first小图入口已接通。**
用户授权工程方提出d：冻结语义坐标的加权差异，对权威一致的完整意图集合取最坏界。
11项定向测试通过（含穷尽小域前缀及双RDF源执行）；逐槽toy中Exact询问2次得到3行
正确答案，Bounded ε=1/2询问1次得到4行（多1行），相同一问预算Exact拒答。
这是机制门，不是总体速度/开放NL/新原生服务结果。详见
[定义](decisions/finite_intent_discrepancy_v1.md)、[验收](report/intent_terminal_20260916.md)。
主NL/共享AND-OR尚未使用这个新入口，full-intent动作的共同选择仍需接通。

2026-09-16：**M0权威模拟用户第一版、M1小图内存修复已验收。**
真实LLM→模拟用户→Neo4j+Fuseki：1模型调用、2次澄清、1最终计划，4行答案匹配，
总在线5.308s。16节点内存重放最大算子输出4118→72行，答案不变。75个不同定向测试
通过，全部托管服务关闭。见[本轮验收](report/simulated_user_memory_20260916.md)。

新入口为 `xgap-nl-user-*`，允许私有gold意图通过实际查询返回权威回复；现实用户不逐题
参与。第一版采用固定有界询问流程，还不是terminal-first信息策略。旧NL-only入口保留。
用户最新要求：先做Exact trace prefix opportunity analysis，再决定统一terminal-first/
lazy搜索器的重构；不立即大改、不扩量实验。见[下一阶段计划](research_next_stage_plan_20260916.md)。
M1整批存储隔离、SF0.1旧OOM重验及M2–M4仍未完成；不能宣称全部内存问题已消除。

[首轮机会分析](report/terminal_opportunity_20260916.md)：仅做只读重放，0新模型/后端/oracle调用；证书缺失时不产生提前认证或收益结论。

## 已封存NL-only首版（历史，尚未接入模拟用户）

12题、72个方法观测均封存评分，72次真实模型调用；53个本轮服务会话已关闭。
该批为未接入模拟用户的NL-only入口，无逐题澄清；strong以模型结构为条件。
这一旧实现事实不代表最终EXACT设计，也不能重命名为已完成模拟交互评价。
Native EXACT/PERFORMANCE均7/12匹配；RDF分别8/12、7/12。四组各4道多跳题
触发2GiB方法内存上限；native各1道变量命名失败，RDF PERFORMANCE另1道被累计
artifact磁盘上限截断，不能据此声称EXACT更精确。11题空参考、唯一非空题10行均匹配。
共同正确题配对时间比中位数native 1.0215、RDF 1.0001，源调用/bytes相同，未证明模式优势。
FedX 12次预算截断；FedUP 11次原生失败、1次模型传输失败，无SOTA效率比较的成功范围。
首批8条零调用配置拒绝单独保留；修正接线后另做首次实际外部观测，没有重跑XGAP。
详见[本轮验收报告](report/nl_strong_first_pass_20260916.md)。
当前工作与验收见[Goal](goal.md)和[本次契约](decisions/nl_conditional_strong_v1.md)。
下述384条均为此前可信模板实验，不能当作本次自然语言结果。

## 历史可信模板结果（不是本轮NL）

冻结提交5d82b6f，native 48题×2模式、same-facts RDF 48题×6方法，384/384封存并评分；
全部托管服务关闭，历次journal pin不变、无indeterminate、无自动重试。全部原始结果保留。

|表示|EXACT正确|PERFORMANCE正确|在线中位数：EXACT / PERFORMANCE|
|---|---:|---:|---:|
|Native Neo4j+Fuseki|48/48|48/48|12.832 / 12.623 s|
|同事实RDF|48/48|48/48|29.319 / 26.552 s|

48题含33空、15非空参考（家族非空数0/4/11），两模式各15/15非空正确。192次XGAP
均strong、1最终计划、0当前题probe/fit/retry/模型、1次本地关系权威。外部固定信息
FedUP两个组合各48次失败，全部有原生extend异常；FedX两个组合各48次预算截断。
不把这些失败当成SOTA速度优势。外部前端192模型调用，已报告79,832token，原usage
字段遗漏通过只读sidecar恢复，未改原receipt。[完整验收报告](report/partial_strong_first_pass_20260915.md)。

配对EXACT/PERFORMANCE速度比中位数native 1.015×、RDF 1.101×；每表示48题源调用
和响应bytes逐题相同，EXACT额外优化没有降低所选估计成本。RDF差距主要在执行阶段，
不能归因于planner改进。单次观测未证明统计显著性、总体模式机制收益或scalability。

## 已实现与已有验证

|环节|实现与证据|范围|
|---|---|---|
|语义/编译/执行|有界semantic DAG、Cypher/SPARQL、协调器及真实双后端|可信结构与支持算子，不是任意NL/图查询语言|
|Strong策略|有限AND/OR、所有声明结果可行后续、全策略先可行后有界改进|保留可行方案；无全局最优/近似比保证；[全策略门](report/global_strong_seed_20260915.md)|
|两模式与信息动作|验证/授权预测、冻结catalog、可选LLM、按需权威、普通profile入口|权限差别已有小图证据；本轮两模式均选便宜权威|
|同请求live链|1模型372token、1计划2源调用、gold一致|一槽提议，非开放NL结构保证；[live证据](report/practical_model_e2e_20260914.md)|
|物理策略/估计|协调器、首跳/逐跳绑定、冻结相对排序|toy迁移未校准；总体排序/regret未证明|
|读取/准备优化|已有同artifact完整读取共享、必要过滤、每请求一次准备|已有真实tiny源调用/行数降低；别名共享仍是未合入候选|
|研究入口|逐题发布、共同fixed-info前端、guard、observer、score、journal及failure replay|本轮384次首次观测，不是重复六轮，不与旧版本合并|

具体历史门见[9月15日审计](research_contract_audit_20260915.md)与各report；不重复已成功门来增加计数。

## 下一阶段准备状态（未执行）

- FedShop固定源码与WatDiv子模块已保存，12模板静态语义清单存在；尚无生成器、
  数据生成或方法运行证据，任何完整模板都还未通过runtime admission。
- q09仅是接入候选；q12/q01用于核对非平凡连接是否可在有界语义内比较。2/4/8源
  属FedShop-derived，不能标成官方20/40源miniature。保持全模板coverage分母。
- 计划先形成有效共同支持与非空答案覆盖；这些后续评价阶段尚未启动。

## 后续优化候选（细节由新计划的阶段门约束）

- 一个时序请求中的重复别名读取涉及约47MB、占该题响应约42%；有等价共享候选，尚未
  合入/测试，不能声称实际延迟收益，更不能直接触发全量重跑。
- 模型usage接口修复、RDF equality-key统计接线、扇出特征及便宜物理改进是候选问题。
  不把key上界当结果行数上界；不用evaluation观测拟合。
- 本轮NL多跳中间结果是优先诊断对象；回到小图检查绑定传播/过滤前移，改善下一版
  非空参考覆盖和累计日志预算隔离。当前结果不支持扩量调参；不自动重跑失败题。
- 当前输入不体现精度—性能权衡；外部比较缺共同成功范围。bounded FedShop只有静态
  准备、未生成/执行；讨论后才决定下一轮机制和验收门，不优化baseline。
- 任意NL结构权威、用户待定义d/epsilon、总体优势、scalability和完整16–20图未完成。

[此前状态快照](status_history_20260915.md)只供溯源，旧“下一步”不生效。
