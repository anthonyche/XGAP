# 后端可评价合同：完整覆盖与逐题成功分开

2026-09-25。承接用户的一天内收尾要求和
[通用优化、批量覆盖计划](one_day_readiness_20260925.md)。

## 目的与边界

合法查询在预先冻结的预算内超时，可以成为实验观测。它不必先被优化到成功，
才能进入正式评价。但答案错误、未知执行异常、证据缺失和源资源无法关闭仍是
当前后端准入阻断。此合同用于独立 gold-query 后端检查；正式方法产生的错误答案
依然是 effectiveness 结果，不能用这个门筛掉表现不好的 baseline。

新增 `xgap-ch6-backend-eligibility-v1`，保留旧 `full_bundle_admitted` 的严格成功语义。
新证书的 `eligible_for_evaluation=true` 表示完整部署覆盖可评价；它独立报告
`all_answers_correct`，并始终令 `full_bundle_admitted=false`、
`formal_campaign_ready=false`。全量仍需通过数据、版本、支持、F6、因子与预算发布审计。

## 证据要求

由 `freeze_ch6_backend_eligibility.py` 从 SHA 固定的输入说明及原始段回执重新计算。
它不执行数据库查询，不调用模型，不修改历史回执。

- 覆盖整个冻结 bundle，顺序一致，无遗漏、重复或重新取样。一个诊断子集不能放行。
- 所有段使用同一精确源码提交、bundle、prepared stores、profile、source runtime、
  源预算及方法/源内存预算。暂不把跨版本累计通过当成同版本证据。
- 每段仍遵循首错停止，关闭及副本回收证明完整；只有资源截断可以转下一段。
- 可接受分类为 `correct`、`source_timeout`、`worker_timeout`、`resource_censored`。
  基于结构化状态判断，不从错误字符串猜测原因，也不把缺失答案当成空集。
- 成功行重新读取 worker、实际答案和独立参考，核验查询及源身份、有序规范化答案，
  并验证零模型调用、至多一次最终计划执行。整个部署至少一次实际正确源往返。
- 源运行回执须匹配请求时限和实际运行模式；每题方法/源内存预算不能与合同不同。

输入字段为 `schema_version=xgap-ch6-backend-eligibility-input-v1`、`source_commit`、
`bundle`、`prepared`、可空的 `source_runtime`、`admission_budgets`、
`resource_limits={method,source}`、按执行顺序排列的 `segments`。文件引用均为 pin。
命令入口接收 `--spec-path`、`--spec-sha256`、`--output`；输出写一次，已有文件不覆盖。

## 接线与公平性

`prepare_ch6_execution_units.py`、`freeze_ch6_mixed_support.py` 和
`ch6_source_runtime.validate_admission` 已接入新证书验证；使用时从原始证据重新核算，
不只信任一个布尔标记。旧回执继续按原严格语义处理。

正式执行配置的源预算、方法/源内存须与新证书一致。NL 完整请求的 worker 总时限
可独立声明，因为它还包含解释和信息获取；不能混同 gold-query 诊断的 120 秒。
实验中必须分别标明方法终止与 study/harness 截断。

诊断超时的题仍保留在五方法 manifest 和支持分母中。TS 原生部署不支持的判定
继续来自接口合同，不能从超时或答错推断。此修改没有优化 baseline 算法或输出。

## 本地验证及真实状态

28 项定点测试通过：原始答案复核、版本/预算/关闭拒绝、子集与重复覆盖拒绝，
新证书接入共享源运行、五方法 manifest、重复数和混合支持合同。全部使用小型
fixture，零数据库/LLM 调用，不属于正式实验结果。

3874119 使用已冻结 `4b80d3d`，其 checkout 和运行参数不受本地修改影响。
用户随后在排队期间取消；已确认零运行/无资源分配。保留旧记录的替代作业
**3874144 已提交**，运行/终态待回收。
该批覆盖 RDF 原索引 5–31，
不能单独满足完整 32 题合同。native 的 24/24 是跨版本累计证据；需完成版本影响
核对和必要验证，不能直接制造同版本证书。当前尚未生成真实完整部署的新证书。

F6 既有 12 次成本/答案与中位数复核证据保留，未重复测量。其最终图绑定仍必须
匹配实际发布单元的源存储、运行配置、预算、准备数据；TS 不可评分项保持 null。
