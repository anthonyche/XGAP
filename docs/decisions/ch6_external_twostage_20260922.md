# 最新方法定义：Two-stage 是外部方法串接

用户在首批运行期间更正：**Two-stage 是外部方法/SOTA 组件的实际串接；LD
（LLM-direct）不需要。** 此指令覆盖原实验计划 §4.1、首次准备及首批预算中旧的
主比较定义。不得把内部算法改标签冒充外部方法，也不得继续为 LD 花费运行预算。

当前实验主对照为 XGAP 与外部 Two-stage。其前端使用原版语义解释方法，后端使用
原版查询优化/联邦执行方法；明确报告组合名称、版本、原论文适用范围、模型替换和
接口配置。原作者前端如果包含探索、执行或重试，完整保留并计量，不能为了宣称
严格两阶段而删掉作者步骤。这里的 two-stage 表示组件串接，不承诺前端无数据库访问。

`xgap-unified-two-stage` 仅是已实现的内部 shared-component 诊断变体，保留 ID 和
原始结果以便复现，不再是论文 Two-stage。`xgap-llm-direct` 退出当前实验计划；
已完成输出封存，不纳入主比较图，也不删除不利结果。

## 原版组合准入

优先核验现有 ARUQULA → FedUP（FedX 执行）的原版串接。ARUQULA 的作者论文明确
使用迭代探索与执行；不是一次文本生成。官方实现报告 2025 Text2SPARQL corporate
和英文 DBpedia 类别第一、总体第二，这提供强外部方法依据，但不代表它在本研究的
跨源、歧义、金融数据上已是最优。

固定组合当前**未通过准入**：2026-09-21 保存的真实原版运行产生 2 次成功模型调用、
1 次成功 lookup、3 次 FedUP HTTP 500，源查询为 0。已验证本地固定 FedUP 的
`TransformUnimplemented.transform(OpTable)` 直接抛出 UnsupportedOperationException；
触发查询是作者原生 VALUES 探索查询。换 FedUP 的下游执行引擎不会自动解决这个
上游 algebra 支持问题。保留 unsupported/setup failure，不能画成成功/零耗时。

候选的兼容替代是原版 ARUQULA → FedX，但必须作为独立组合冻结、准入并说明选择
依据；不能暗中切换引擎后仍叫 ARUQULA+FedUP。不修改作者 prompt/搜索/输出以改善
成绩。外部方法仅支持 RDF 时，XGAP 必须在同事实、同 RDF 部署下对比，不能与本轮
native 延迟直接计算 speedup。

来源：[ARUQULA 原论文](https://arxiv.org/abs/2510.02200)、
[作者代码与比赛记录](https://github.com/AKSW/ARUQULA)、
[FedUP 官方代码和使用说明](https://github.com/GDD-Nantes/fedup)。

## 本轮停止和保留

`ch6-first-real-20260922-v3` 已停止，服务组全部关闭。共封存 25 个 cell：12 个
controlled（6 XGAP、6 旧内部变体）及 13 个 NL（4 XGAP、5 旧内部变体、4 LD）。
1 个 LD cell 因更正时中断而未封存，4 个尚未尝试；不能把它们算成方法答错或自行重试。
仅继续尚未尝试的 2 个 XGAP NL case，以补齐同一预选 6 题的 XGAP 实测；不再
执行旧内部对照或 LD。原始 manifest、计数和版本不改写。

补充：两道剩余 XGAP NL 已在独立 continuation v1 中完成并关闭服务。
当前有效结果是同 6 道问题的 12 次 XGAP 执行，全部匹配参考；
见[真实结果报告](../report/ch6_first_real_20260922.md)。外部组合仍未通过验收。

旧 864-call 提案已失效。外部方法是多调用算法，不能假定每题一次 API：最终总预算
须按原版准入观察和明确调用上限重新冻结。内部分量扫描只对适用的方法开放。
