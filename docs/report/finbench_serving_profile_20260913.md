# 9月13日：真实 FinBench 服务输入已冻结

本轮已将小图专用发布入口扩展到完整源快照，并一次完成同事实数据物化及修复后的
真实配置发布。原120题、训练/评价分组、参考答案与baseline实现都保持不变。
这是进入真实实验所需的输入工程，不是已跑出新方法分数。

## 产物和实测准备成本

| 项目 | 结果 |
|---|---|
| 源事实 | 全部18张表，55,604实体、309,577关系；合计365,181源记录 |
| 同事实物化 | 7.146秒；图RDF618,038,554字节、control RDF49,717,340字节；保留平行边身份 |
| 新catalog | 59,587条：55,604实体、3,967控制值、9谓词、5类型、2源；文件13,540,371字节 |
| 配置发布 | 7.916秒，包含加载校验；不含此前失败attempt和物化时间 |
| 一次配置加载校验 | 1.566秒，是准备阶段的实测值；正式请求实际加载费用仍须计量 |
| 模型/后端/训练/方法运行 | 全部0 |

Native加载文件130,648,495字节；上述RDF文本字节是表示大小，不是backend存储量或
查询网络开销。graph与control共享全部55,604实体身份；13类关系表对应9种谓词。
输入发布验证了两模式与冻结统计，不意味着这些事实已经装入运行中的数据库。

## 实现改变和它说明什么

新增的离线publisher流式校验大加载文件，保留runtime小元数据/catalog的16MiB上限。
所有源实体都进入catalog，提供带类型business ID、原ID和观察到的名称；有歧义的
ID/名称保留多个候选，不声明权威身份。catalog不枚举路径或按hop扩展，也不读取
评价问题、gold或答案。控制类别进入有限候选词表，金额/时间等仍可作为typed literal
出现在查询中；没有为了catalog大小移除源事实。

统计由实际源文件导出：graph实体+关系作为工作行，control实体作为工作行，平均
宽度按声明的源序列化计算。它们是工作量代理，不是假称已知查询选择率/结果行数。
原32条tiny训练产生的model字节与参数完整保留，只通过已有deployment接口绑定
新snapshot/statistics；迁移尚未校准，没有重新训练，不能据此宣称排序更准或更快。

发布器的成本主要是顺序文件校验与扫描、实体/控制值去重和排序。设源字节数B、
实体数V、不同控制值C，主体为O(B+(V+C)log(V+C))加字符串处理，内存O(V+C+batch)。
它不依赖查询hop展开；planner算法没有因此改变。完整数据离线输入已经可以用秒级
准备，下一步的实际瓶颈要通过真实运行的解释/grounding/规划/执行分项测量确定。

## 验收和保留的失败

- 复用已接受的小图文件验证新入口，未重复旧native、LLM、baseline或训练门禁。
- 五项新风险检查已接受：全实体ID/名称/控制类别与歧义、权重不变及新统计的估计
  domain、篡改/不一致快照拒绝、大文件流式校验、完整五实体/十三关系schema覆盖。
- 开发首次collection暴露额外右花括号；修正后3项通过，剩余测试缺必填构造参数，
  修正后只重跑该项并通过0.24秒。
- 第一次真实发布（516fbb4）因小图schema helper遗漏Loan别名而终止；没有模型或
  后端调用，失败文件保留。用极小的完整schema replay修复，新增1项0.22秒通过。
  在新目录由161ef2e发布成功，没有重跑源物化，也没有覆盖第一次失败。
- 实际文件审计通过：catalog/bindings、模型、prompt、源summary与profile pins一致，
  模型内容不变，五类实体数量与完整源manifest一致，数据版本与冻结120题metadata一致。
  审计只读取人口metadata，没有读取问题/参考答案/方法结果。

## 当前系统状态与下一项工程

有界普通NL→单次解释→冻结grounding→Ptime估计选择→一个最终双库计划已有真实
小图正确答案证据；本轮进一步交付完整真实数据的可加载输入和双模式profile。
实际SF0.1查询、两模式准确性/成本、外部SOTA比较和规模实验尚未执行。

下一milestone：共同运行预算、资源/watchdog与成本记录；接上原始外部方法的共同
输入/评分接口，并先验证具体新边界。之后进行主评价，再做规模和消融。大集只用于
评价/必要真实接入，不作日常debug环境。XGAP-RDF多endpoint实例的compiler/estimator
身份兼容仍需检查，不能因RDF文件存在就称该方法路径已接通。FedUP/FedX已能运行，
不替它们补语义或调结果。120题评价组33空/15非空仍须按语义/空非空分开报告。

用户的暂停已在9月13日12:00到期，12:08恢复，现有heartbeat已恢复每小时推进。
整体Goal继续active；核心Sep14 17:00、真实实验Sep18目标保持。

## 证据定位

- 执行代码：物化35d9449，发布161ef2e。
- 根目录：`/Users/anthonyche/xgap-data/finbench-sf01-serving-20260913-v1`
- [实际profile](/Users/anthonyche/xgap-data/finbench-sf01-serving-20260913-v1/native-profile-v2/profile.json)
- profile SHA: `0d77ce65976c4e7520ffdc7926b1c40398ec8f5bf73ee709343dcd27767f152c`
- audit SHA: `eeb274f1953497af3e0a66f7c092854846bb212731812135528dc64a756ec5bd`
- [提交审计](../../experiments/artifacts/finbench_serving_profile_20260913.json)
- [第一次发布失败](../../experiments/artifacts/finbench_serving_first_attempt_20260913.json)
- [发布契约](../decisions/finbench_serving_profile_v1.md)

本轮全部执行进程已经退出，没有启动数据库或模型服务。
