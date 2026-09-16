# XGAP Current Status

2026-09-16。**自然语言端到端首版已完成；下一阶段计划已更新，执行保持暂停。**
用户已认可比较路线，最新要求是“先分析、更新计划，暂时不要开始执行”。
见[下一阶段分析与计划](research_next_stage_plan_20260916.md)：小图执行优化、作者原查询
的有界FedShop外部对照、更好的NL评价覆盖；模式理论由用户推进。此次仅改文档。
最新设计纠正：EXACT需要可查询的权威模拟用户来替代现实用户逐题参与，不能因本人
没答就失败；gold意图可以私有保存在oracle中。已加入M0，尚未实现或实验。
见[模拟用户契约](decisions/simulated_user_authority_v1.md)。
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
- 计划先形成有效共同支持与非空答案覆盖；本轮不启动任何新测试或实验。

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
