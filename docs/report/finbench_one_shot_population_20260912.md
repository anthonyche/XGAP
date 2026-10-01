# 本轮收尾：真实 FinBench 评价输入冻结，9月13日12:00恢复

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: authorized offline preparation and audit
- Origin Date: 2026-09-12, Asia/Shanghai
- Verification Status: actual 120-group input build and artifact audit passed; no method campaign executed
- Version Label: finbench-v010-sf01-one-shot-120-v1
- Execution code: 49aaff0; five new tiny checks accepted before this run (0.51s), not rerun

## 本轮完成内容

真实 LDBC FinBench v0.1.0 SF0.1 的120组评价输入已经生成并冻结。每类40组，
总计24开发、48估计器训练、48评价。每个结构/时间分层按2/4/4分配；旧48题中
16个人物锚点、16个账户锚点已排除，新F3时间窗彼此不重叠，也没有与旧题同风险
标签的时间窗达到0.8交并比。抽样依据固定源结构/时间与seed，在答案计算前封存。
它是固定图上的新参数组；图事实重叠、共享三个模板，不代表独立数据集或未见模板。

每组均有普通NL、独立原始CSV参考答案，以及隔离的gold语义程序/参考SPARQL。
运行输入不含gold、答案或source assignment。360个请求/参考/gold文件与selection
共361个校验值通过核验；120个ID与家族内group均唯一，分组没有跨split复用。
三个金额/类型规范化规则在方法运行前确定，保留行顺序和重复次数，不能修复答案。
错误或执行失败即使遇到空reference也不会记为正确。

一次离线构建耗时 **5.400秒**，零模型、数据库、方法、训练或fit调用。这是一次性
输入预处理时间，不是在线查询延迟，也不是catalog构建或完整系统的速度结果。
没有在服务器提交作业，没有重跑已成功门禁，也没有执行新消融或优化baseline。

## 实际参考答案分布

表中是非空答案题数/总题数，空答案保留在原分母中：

| 查询语义 | 开发 | 训练 | 评价 | 全部 |
|---|---:|---:|---:|---:|
| 直接转账到受阻公司账户 | 0/8 | 0/16 | 0/16 | 0/40 |
| 时间严格递增、最多3跳、受阻medium | 0/8 | 3/16 | 4/16 | 7/40 |
| 按风险筛选后聚合公司转账排名 | 5/8 | 9/16 | 11/16 | 25/40 |
| 合计 | 5/24 | 12/48 | 15/48 | 32/120 |

120题共88题为空；评价组33题为空、15题非空。仅从分母计算，永远返回空表就能在
评价组得到33/48=68.75%的答案exact match；这是分布诊断，不是一次实测baseline。
因此总体EM必须伴随空/非空、查询语义分组、失败率和截止前正确率。当前F1组可以测
空结果处理和执行成本，不能证明成功召回非空直接转账答案的能力。不要因为看见此
分布而替换已冻结题目；若以后增加非空/歧义专题组，须另立明确协议、保留本组并
分开报告，不能悄悄改变主评价分母或按方法成功挑题。

这些题使用business ID明确锚点，三种手写等价措辞共享语义模板；它们测NL组合与
执行，不证明人名歧义消解或未见模板泛化。独立CSV evaluator已通过tiny语义测试，
本次是实际reference生成与文件审计，不等于120题已在XGAP/外部方法上执行正确。

## XGAP当前进度与仍未完成项

有界research backbone已有实际证据：普通NL经一次真实LLM解释、确定性lowering、
冻结catalog绑定、多个合法计划仅估计选一个，最后在Neo4j与Fuseki执行并返回独立
正确答案。最新金融开发题为1次模型调用、9次后端子查询、核心在线约3.375秒；
它是一条曝光开发题，不能推为整体准确率或相对SOTA提速。
[前轮真实闭环证据](compact_financial_nl_20260912.md)。

已实现两模式配置、有界top-K、Ptime估计选择、冻结估计器接口、一次最终计划、
普通请求录制/评分及独立输入准备；实现与局部测试、真实集成和性能结论分开报告。
精度/性能优劣、估计器排序质量、外部方法优势、规模曲线仍未测。

正式campaign仍未就绪：还需冻结真实SF0.1 serving profile/catalog/statistics及
同事实RDF物化；接齐共同输入/评分、资源与调用预算、运行时watchdog及源级成本
记录；之后才运行已批准的主评价和FedUP/FedX对照。外部原实现只做到可运行并如实
计分，不替它们补语义或调成绩。主评价/规模之后才做消融。小图仍是开发环境。

## 用户要求的暂停与下一次恢复

本轮milestone已经完成，收尾提交后暂停。现有xgap恢复任务已更新并核验为中午触发，
保存明确的9月13日12:00北京时间门限；首次到期恢复后才恢复每小时推进。
**北京时间2026-09-13中午12:00之前不得开启下一轮开发、实验、模型/数据库请求、
训练、baseline运行或服务器轮询。** 该最新指令覆盖历史自动继续/每小时推进安排。
整体Goal未完成，保留active目标；不要为暂停误标complete或blocked。

恢复后从真实serving输入/共同评价接口准备继续，不重新跑本轮抽样、五项已通过
检查、模型成功题或baseline接入门禁。Sep14 17:00核心与Sep18真实结果目标不变。
如需要改变研究人口或主图结论范围，再以具体材料与用户讨论；今晚不启动此扩展。

## 可核验产物

- 本地目录：`/Users/anthonyche/xgap-data/finbench-one-shot-population-20260912-v1`
- manifest SHA-256: `181c1426752fbed9a287ba76b50a05834bfe910c07789eeac145a3c3fd520fba`
- selection SHA-256: `2cb81d785fc6d5784ba8e0415c1e23319c0f19e8fb91d06a2ae7378580e311c2`
- audit SHA-256: `98cd76d9b450b5f915813f7079ecd82e3d67e3d1b79ecbd446c28aae446d5e63`
- 原archive SHA-256: `f0359b5c4515cd5d86349b4a11a7470f6f153e42c5ac21c59e70f5c0d0b37a60`
- [提交的审计摘要](../../experiments/artifacts/finbench_one_shot_population_20260912.json)
- [固定抽样与语义契约](../decisions/finbench_one_shot_population_v1.md)

以上文件保持封存；本轮没有未结束的构建进程或新启动的数据库服务。
