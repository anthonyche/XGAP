# 金融语义进入普通确定性链路：2026-09-12

本轮实现了边属性读取、字段间比较和显式毫秒时间字符串比较。三类金融gold语义程序
现在通过普通semantic compiler、Ptime候选域、冻结估计器及单个最终计划，实际运行
在分担必要事实的Neo4j5.26.30和Fuseki5.6.0上。全部与手工推导答案一致。
这是8实体/16关系小图上的确定性开发证据，**不是金融NL准确率或真实SF0.1评价**。

## 实现和语义边界

- 边形式Match以一个普通源查询返回边、两端身份及指定金额/时间属性；不隐藏二次fetch。
  相同端点的平行边保留独立身份。RDF需要已有reified-edge契约，plain triples不支持。
- Filter增加右字段以及显式`timestamp_ms`类型；仅合法固定格式
  `YYYY-MM-DD HH:MM:SS.mmm`，没有时区转换。旧字符串排序真值保持不变。
- Project增加有限标量literal，用于标注固定长度分支；OrderLimit的显式null表示只排序，
  防止F1/F2被任意大limit悄悄截断。F2使用1–3边分支、递增时间和无重复账户约束。
- 边Match的端点/边身份可进入已有single-bind策略，仍保留最终join、独占消费者检查
  和P(1+2J)域界。没有全组合搜索、候选试跑、自动repair或retry。
- v2冻结估计器将边读取声明为one-edge-path工作量，记录新lowering未经校准；原系数、
  维度和训练记录不变。新参数契约v2与通用金融语法prompt已有接口和零调用检查；
  尚未发出金融NL模型请求。历史wire记录继续绑定旧hash/code，不能静默改签。

[语义、复杂度及验收契约](../decisions/financial_binding_semantics_v1.md)。

## 实际证据

11项不同的新风险检查通过：首次8项中7通过，1项是测试要求金额字段必须带反引号，
而编译器合法输出未加引号；删除过严格式断言后只补跑此项，通过。另3项覆盖endpoint
entity-hole绑定、一个明确指定的RDF endpoint-bind微查询，以及provider输入不依赖gold。
没有重复已通过的历史suite、3条新RDF选择执行或native门禁。

真实双库收据：
[financial-binding-native-20260912-v1](/Users/anthonyche/xgap-data/financial-binding-native-20260912-v1/receipt.json)。
每题的`F*-plan.json`先封存全部估计、候选域和选中计划，之后才启动服务；逐调用
artifact/原始ExecutionReport与最终结果封存后，才读取独立答案评分。

| 语义 | Operators | 合法计划 / 构造上界 | 可估计计划 | 实际源查询 | 独立答案 |
|---|---:|---:|---:|---|---|
| F1：直接转账、封禁账户、公司金额 | 12 | 6 / 9 | 3 | Neo4j4 + Fuseki1 | 公司1：账户2=66；账户3=9 |
| F2：≤3跳严格递增时间、无环、封禁medium | 24 | 6 / 11 | 3 | Neo4j4 + Fuseki2 | 4行，与参考全部一致 |
| F3：风险medium、去重账户后公司金额排名 | 13 | 6 / 9 | 3 | Neo4j4 + Fuseki1 | 公司1=56 |

三题各执行一个选中coordinator计划；没有执行未选中的native计划。总16次最终源查询，
另13次Neo4j离线装载/约束操作及1次Fuseki装载，启动健康检查单独留档。模型、baseline、
新训练、fit、当前题probe均0。拥有的Neo4j31402和Fuseki31444均已终止。

规划44.283/49.897/42.827ms；scheduler432.591/171.799/72.709ms，是单次开发诊断，
含首次数据库执行影响，不能作为稳定延迟、预测误差泛化或相对提速结论。原收据字段
`offline_prepare_ms=150.848`实际混有3题规划及其记录开销，不是纯一次性准备成本；
后续脚本已改为分别记录输入准备与开发准备+规划，未为这项记账更名重跑查询。
服务启动7818.306ms、fixture装载970.686ms单列。128-byte工作单位是显式开发proxy，
不是测得的网络字节。旧输入seal仍对应执行时的代码；随后仅增加provider接线及该
记账字段修正，追加检查分别注明，不把旧收据改成新运行。

## 结果说明了什么，还缺什么

已证明金融工作不必依赖旧prepared-plan runner：关系属性、时间/环路约束、跨库join和
聚合能经普通确定性骨架执行。结果保持parallel transfer及多个medium的正确去重行为。
还不能说明NL解释准确、估计器选得好、两模式形成Pareto优势或XGAP快于外部方法。
金额输出当前是原始SUM；本轮答案恰好是整数，未覆盖三位小数取整差异。真实评价前
须冻结共同的金额比较/精度约定，不能靠临时修改某方法的答案取得一致。

每题另外3个合法边bind计划出现`unavailable_unseen_work`，原因均为冻结训练未覆盖
`backend.neo4j.path.bind.calls`。未把未知估计当0，也未选择实际执行后更快的计划。
对应rewrite已有编译和RDF微查询证据，Neo4j边bind尚缺实际执行证据。因此下一步用
独立极小训练图补这个新工作类别，同时验证该native边界；复用旧观测文件，不重跑
28条旧训练，不以本轮金融题训练，然后冻结新artifact并保留原模型。

随后完成新的金融source schema/catalog/profile，做一次普通NL-only请求；本轮gold
program不能进入模型输入或替代模型输出。最后才冻结未曝光真实样本、reference和
预算。继续用户批准FinBench→FedShop优先级，baseline如实记录、不优化；remote3804210
不操作，Sep14 17:00核心目标、Sep18真实结果目标及active Goal保持。
