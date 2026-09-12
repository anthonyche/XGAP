# 金融 NL 输入已接入；首个真实请求在 Interpretation 阶段失败

本轮完成了金融小图的可复用 source schema、45项冻结 catalog、双模式 profile，以及
普通逐请求运行/评分接口接入。一次真实 Qwen 请求返回了16个operator的程序，但它未
通过已有参数契约，未进入 grounding、planning 或最终查询执行。不能称金融 NL 闭环
已成功；此前三类确定性金融程序和端点bind的实际成功仍保留其各自范围。

[范围及验收契约](../decisions/financial_nl_profile_v1.md)。本轮只用了已接受的8实体/16边
小图，复用32样本冻结模型；没有训练、baseline、大数据、试跑候选或自动重试。

## 输入与实际结果

问题要求：Alice所拥有的账户，在2020-01-01至01-04（两端包含）直接转账到公司拥有
的被冻结账户；按公司及收款账户汇总金额，平行转账分别计数，并按金额降序、ID升序
返回全部结果。独立fixture算术预期为公司1/账户2=66、公司1/账户3=9。此题已开发曝光，
不用于未见问题准确率评价。模型只收到NL和可复用schema，没有gold程序/物理计划/答案。

| 边界 | 本轮证据 |
|---|---|
| 离线输入 | 从固定映射/装载字节提取schema和实体名，publisher不读取问题/答案；45项catalog。原始输入与model文件均校验hash。 |
| 模式 | precision K3、performance K1均通过新输入预检；实际仅调用performance一次。 |
| 模型调用 | 1次，3212 input / 1970 output tokens；完整原响应已保存。 |
| 准入结果 | `no_admissible_interpretation`；唯一candidate的Project含非法`kind:aggregate`及`func`。 |
| 后续阶段 | grounding/planning/最终源查询均未发生；final plan执行0次，源查询0次。 |
| 评分 | 按失败记录EM=0、row multiset F1=0；不是返回空集得到正确答案。 |
| 资源 | 一次装载13个Neo4j动作及1个RDF动作；健康检查单列；两个自有服务均已终止。 |

普通core在线10,308.143ms，模型边界约10,300.283ms；记录wrapper为10,335.665ms。
这些是单次失败的实际成本，不是查询性能对照。离线profile发布39.464ms（包含验证），
runner准备41.342ms，服务启动8,010.452ms，装载1,072.853ms，均另列。已有训练的历史
成本仍在冻结model provenance中，不属于本次在线调用或新增训练。

[完整收据](/Users/anthonyche/xgap-data/financial-nl-native-20260912-v1/receipt.json)；
[普通请求记录](/Users/anthonyche/xgap-data/financial-nl-native-20260912-v1/request/receipt.json)；
[原模型录制](/Users/anthonyche/xgap-data/financial-nl-native-20260912-v1/request/interpretation.json)。
原录制文件SHA-256为`42cd06906038730990f0c16cc9ed356ecce6cc62feea65b28efee65f2137c39f`。
Neo4j36522 exit0、Fuseki36562 exit143；均由当前runner结束，无重启。

## 失败告诉我们什么

直接触发拒绝的是非法聚合投影。进一步静态查看原响应还发现：投影出的边身份被用作
`transfer_edge.createTime/amount`隐式属性访问；控制属性被分配到不含这些属性的graph
source；身份列与business ID同名冲突；Alice没有entity hole；公司被额外加上blocked
条件；缺最终排序。这些是保存响应中的问题，不是分别执行后测得的失败次数。

运行期catalog没有构建，也没有慢在catalog。现有确定性core支持此类查询所需的有界
语义，但这次模型没有正确使用接口。wire当前只约束envelope；本地参数v2准入保留了
拒绝行为。旧通用prompt虽提到新edge Match，却未完整说明Aggregate/OrderLimit参数，
因此识别出需要补齐的指导缺口；不能断言它解释了模型的全部错误。

## 已采取的工程措施与下一步

新增显式`financial-binding-v2`语法profile，补完整聚合/排序、身份列与属性读取、源字段
归属的通用指导。无问题专属程序或答案；不放宽编译器/准入、不补写模型响应。v1仍可
显式加载，旧prompt及冻结profile保持原样。新参数默认v1；后续使用v2必须显式选择。

本轮4项独特检查均首次通过：输入/源身份/双模式预检与装载hash漂移检查2项（0.26s），
原失败不变回放与v2两模式完整wire预算检查2项（0.20s）。没有重复已通过的旧检查。
原失败的request和原始响应另存为仓库中的failure replay，绑定原录制hash。

下一步是显式v2 profile的一次必要真实金融NL边界，使用同一曝光开发问题，保留v1失败。
不自动fallback、不用gold替代响应、不做多候选实际试跑或估计器再训练。新prompt目前
只有本地接口证据，尚无实际模型成功证据。金融NL验收后再冻结真实样本、独立reference、
金额精度和运行预算；Sep14 17:00核心与Sep18真实结果目标不变。
