# 2026-09-13：去重/聚合实现与模型解释分别验收

本轮完成版本化贡献粒度语义，真实 Neo4j + Fuseki 确定性链给出正确非空答案；
同轮的一次普通 NL 请求解释失败，完整保留。不能把正确的 gold-intent 执行当作
NL 准确率，也不把模型犯错描述成 compiler/planner/execution 没有实现。

## 实现了什么

cba95be 增加独立 compact-v2 schema、prompt、provider/profile 与 lowering。
`contribution_by` 指定计一次的对象，同时保留所选字段所属实体/边的身份。
例如按公司/账户计贡献时，SUM 对应的转账身份仍然保留；多个合格登录证明不会
把同一笔转账重复计算，同金额的不同转账也不会被合并。使用既有 Project DISTINCT，
未增加底层算子，没有修改 planner、冻结估计器或 baseline 算法。

有界范围：同一聚合块只支持一个存储节点/边变量的聚合粒度；SUM(转账金额)和
COUNT(转账)可以一起输出，SUM(账户余额)与SUM(转账金额)不能混在一个块中。
投影计算O(q log(q+1))时间/O(q)空间，原有多项式lowering与64算子上限不变。
它不保证执行时间为多项式，也不保证所选计划是实际物理最优。
[冻结语义及完整边界](../decisions/compact_contribution_v2.md)。旧 v1 不接受新字段，
新 v2 不重标或修复旧响应。旧真实 group2 四次失败继续保留。

## 检查和真实结果

4项新检查首次通过，1.49秒：多证明/同金额平行边、共享全局SPARQL一致、保存失败
重放和有界拒绝、两模式冻结配置及单调用wire。没有重复原成功门禁。
独立小图原6笔转账合计56；增加10.125的独立平行转账后7笔合计66.125，
同时增加登录证明不放大金额；显式SUM(DISTINCT amount)仍为56；账户计数为3。

| 链 | 结果 | 模型调用 | 最终计划 | 源调用/传输 | 完整在线时间 |
|---|---|---:|---:|---|---:|
| 普通NL，新v2 | 解释被拒绝，EM=0 | 1 | 0 | 0 / 0 B | 4.135 s |
| 独立gold intent → v2 lowering → estimated plan →真实双库 | company_id=1、total_amount=56、transfer_count=6；EM=1 | 0 | 1 | 6 / 5,295 B | 1.322 s |

NL模型2387输入/506输出token，把`High risk`变成`High`，并用禁止的`xgap_id`
引用计数；实际在后者的合法性检查处拒绝，前者是保存响应中可见的语义偏离。
未补值、删约束、修响应或重试。这是一次解释质量失败，不是catalog构建或GPU障碍。

确定性链从5个可用估计候选中选择1个，构造上界9，选择为placement-0/coordinator；
规划50.221ms，执行973.864ms，其他在线入口/记录费用包含在1.322s中。
另外4个候选没有试跑。估计14.290ms仅用于排序，不据此声称时间预测准确或排序已最优。
未重训、重建catalog、重装数据、调用baseline或跑oracle。

真实NL gate首次准备因参考记录把transfer_count当文本而退出；无数据库/模型调用。
88bfbec明确fixture计数类型integer，一项针对该失败的检查通过0.32秒。该准备失败
19624bf9记录保留；随后模型实际只调用上述一次。dd8bdb7另加独立确定性真实gate，
没有读取模型回答，其答案只与事前手写算术核对，未覆盖NL的EM0。

所有相关控制器已终态：预检94249 exit1、NL97260 exit1、确定性60371 exit0。
NL与确定性服务进程组、observer均确认关闭，冻结输入保留。

## 这对下一步意味着什么

去重/聚合的确定性功能已实现并测通；Interpretation仍可能产生错误，是要测量的
effectiveness结果，不能无限追求每个模型输出都正确。保留有界拒绝、实际错误率、
无自动repair/retry，不继续围绕这道失败题调prompt或重跑大数据。

继续已批准且未运行的固定语义实验，补齐真实非空结果与资源记录；后续NL使用
明确冻结版本和原顺序、保留所有曝光与分母。不同语言/prompt版本分开报告，不把
混合开发轨迹称为一个同质版本的论文总体结果。FinBench/FedUP/FedX优先，随后
有界FedShop，机制消融最后。当前还不能宣称整体准确率、提速、估计器排序收益或
scalability已获证明；本轮没有完成整套18图。

## 继续真实固定语义评价：未运行 groups16–19

保持原native profile、原金标准程序、原冻结估计器和预算，零模型、每题一个最终
计划；新的compact-v2并未用于这四题，因此不能把其结果归因于新解释语言。
只按原顺序处理尚未执行的题，不重跑旧wrong/censored题，显式记录dd8bdb7实现epoch。

| 组/语义 | 实际答案 | EM | 完整在线时间 | 源调用 | 源传输 | 方法峰值RSS |
|---|---|---:|---:|---:|---:|---:|
| 16/时间递增路径 | 正确空结果 | 1 | 30.164 s | 6 | 54.129 MB | 1.770 GB |
| 17/风险聚合 | company2036：9,428,080.26 | 1 | 17.923 s | 5 | 31.191 MB | 0.922 GB |
| 18/风险聚合 | company1581：2,249,563.92 | 1 | 16.498 s | 5 | 31.197 MB | 0.855 GB |
| 19/时间递增路径 | 正确空结果 | 1 | 29.104 s | 6 | 54.128 MB | 1.657 GB |

MB/GB为十进制；原方法预算仍为2GiB。每题6个估计候选，选择coordinator，均只
执行1个计划、替代执行0。4题全部正确，其中2题非空，提供时间格式修复后的新真实
非空聚合证据；不是旧错误题回测，因此不能直接归因或比较修复前后提速。
也不据这4题外推48题总体准确率、baseline速度差或估计器排序收益。
控制器52511 exit0、两个源进程组及observer全部关闭；包耗时104.287秒。
Native fixed下一组20；原groups0–19全部结果和版本边界保留。

[本批逐题JSON](../../experiments/artifacts/native_next_four_20260913.json)、
[CSV](../../experiments/artifacts/native_next_four_20260913.csv)。原始run-0004收据SHA-256
`3bf114595a1acf55b5c904a57ae955b1e52edf0742609bdd8c58b5535b0e44a2`；
原生campaign目录中的`groups16-19-audit-v2.json`封存完整关联，v2仅纠正准备收据字段名，
所有结果/时间未改。当前磁盘约11.9GB可用，仍需遵守6GiB保留与12GiB包输出预算。

## 可复核证据

[结构化记录](../../experiments/artifacts/compact_contribution_20260913.json)、
[两链CSV](../../experiments/artifacts/compact_contribution_20260913.csv)。
- NL原始收据：`/Users/anthonyche/xgap-data/compact-contribution-native-20260913-v2b/receipt.json`，SHA-256 `fcb8eede26a32347d592ac877ec94da8deff0ade3e0c61628230c27210c4939d`。
- 确定性原始收据：`/Users/anthonyche/xgap-data/compact-contribution-fixed-native-20260913-v2/receipt.json`，SHA-256 `2ee8fe83ee359ba22aeda4211756475d1581e3a8569414c1f60033f61330d08a`。
- 上述结构化记录 SHA-256 `7d79b3cea14077dca699872f0bdf036d458e12e06e1211ed3596b6dc4763312d`。
