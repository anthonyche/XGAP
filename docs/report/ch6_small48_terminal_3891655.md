# 48题接续3891655：已完成两域、计量修复与剩余39项

2026-09-27。用户先读到Slurm RUNNING/compt321/03:26:38，随后日志写出完整
`accounting_incomplete`停止回执及归档。调度器最终State/Elapsed尚未单独回收，
不能把先前RUNNING快照当成现在仍在执行；接续提交前须核验历史终态。

## 原始证据

- 归档：`/home/hxc859/xgap-small48-continue-3891655.tar.gz`，8,924,732 bytes。
- SHA-256：`a5b5e6430f511e966146c583ae215bfabf6c4350fac10869109dce0a38748ce2`。
- 本地：`/Users/anthonyche/Downloads/xgap-small48-continue-3891655.tar.gz`。
- 验收目录：`/Users/anthonyche/xgap-data/outputs/xgap-small48-terminal-3891655-v1`。
- 2,057份索引文件大小/hash均匹配，安全展开31,382,423 bytes；无路径越界或链接。
- 代码：`2a8e16e3b03bca4ef075454ef23c9eaff5631e8b`，实验算法与f40dfa9一致。

本次封存135项，父作业保留42项，合计177/216，无重复、无未封存项；
余下39项全部在D2-rdf。D1、D3各72个适用请求已完成；D2-native的32项已完成。
这不是177道不同问题，仍是冻结的48题乘适用方法。

## 已完整领域的答案结果

| 方法 | D1正确答案/适用请求 | D3正确答案/适用请求 | D1/D3 probe次数 |
|---|---:|---:|---:|
| XGAP | 15/16 | 16/16 | 8 / 8 |
| NP | 15/16 | 16/16 | 0 / 0 |
| SH | 15/16 | 16/16 | 5 / 4 |
| GR | 15/16 | 14/16 | 18 / 16 |
| TS | 无可评分答案；4方法错误、4观测截断 | 无可评分答案；2方法错误、6预算截断 | 不适用 |

D1四内部方法的同一COUNT入口失败保留。D3 GR有两项执行失败，其他内部方法
完成全部16题。TS每域只有8个RDF请求适用；原生不支持位置不作为错误，研究截断
也不冒充基线答错。这里不把TS写成已完整观测的0%语义正确率。

所有177项状态：154 answered（答案EM均1）、4 proposal_failed、6 method_error、
9 harness_budget_censored、1 harness_observation_failure、2 execution_failed、
1 upstream_source_failure。D2还未完成，不从其部分结果外推全域平均值。

可直接确认probe已激活、XGAP和NP执行动作不同；不能仅凭调用次数宣称probe带来
总延迟收益。已测内部可评分解释的loss为0，保留真实零值，不人为制造阶梯曲线。

共同成功题的条件平均E2E（秒）如下；D1取四方法共同成功15题，D3为14题，
不能和不同成功集合的条件均值直接混用，也不是全部请求的无条件成本。

| 数据集 | 配对题数 | XGAP | NP | SH | GR |
|---|---:|---:|---:|---:|---:|
| D1 | 15 | 25.469 | 25.667 | 19.449 | 21.690 |
| D3 | 14 | 58.889 | 58.299 | 48.731 | 54.154 |

这组数据未显示XGAP相对NP的明显平均E2E收益，SH在此配对总体更快。两域正确率和
实际probe调用可直接报告；更强的性能优势叙事目前没有证据，不能通过调整数值获得。
派生逐项、分组以及计量补记表位于验收目录的`analysis/`，包含
`D1-D3-paired-common-success.csv`和`D1-D3-dataset-method-actual-metrics.csv`。
后者分别报告all-sealed与answered-only、有效数、缺失数、截断数与计量范围。

## 最后失败与批次停止是两个问题

末题：`D2-test-uniform-witnessed_sum-000-W1-NP`。

1. 工作进程完成一次模型调用、一次最终计划执行；4次后端请求，执行状态为
   `execution_failed`，内部错误为`timed out`。第4条源响应HTTP 200但未完整读取，
   已读15,728,640 bytes，观察记录为IncompleteRead/source_transport；没有触及64MiB
   响应限额。源读取、工作进程预算和停止后的源关闭共同形成此失败，不推断为语义错误。
2. 外层首先等待`observer.snapshot()`，失败后跳过了从已验证worker回执复制模型用量。
   后续源已停止并成功封存，外层却仍为model_calls/input_tokens/output_tokens=null，
   导致全局`accounting_incomplete`。这是实验执行器的异常路径缺口。

原worker回执、core和interpretation一致记录**1次模型、2,649输入、427输出token**；
它们均由原外层partial_worker_files pin绑定。可新增计量核对记录，不需要重跑模型。
核对后的本轮用量403 calls / 728,069 input / 82,711 output；含父作业累计
**468 calls / 868,493 input / 103,775 output**。旧回执的null不覆盖，来源单独标记。

末项两个源进程均已实际回收（143），phase seal成功、late/persistence均0，
invocation all_owned_closed=true且无error，临时serving副本已回收。
本次通用修复只将已通过身份校验的worker用量提前复制，源失败仍然失败；
不会将其改成正确答案，也不会放松查询/观测预算。

## 下一项

按原顺序只接续39项，保留全部177项状态和旧文件。新接续合同要同时绑定原42项、
第一接续135项、补充计量证据及原216请求清单。继承完整累计用量，并以真实Slurm
历史Elapsed计算剩余6小时活动分配预算；不得重置墙钟或默默忽略人工交接政策。
新版本仅改变执行器计量与显式恢复，不修改语义入口、planner、方法配置、题目或源。

本轮48题全部适用请求尚未执行完，规模/并行/参数扫描也不能由这些结果替代。

## 已验证的39项接续包

- 精确源码：`f1b2583e1b1c7068d6e335cfad60b525aaddf0b2`。
- 本地包：`/Users/anthonyche/Downloads/xgapfinal39f1b2583.zip`，8,686,454 bytes。
- SHA-256：`d932231d30b8cd691a7b1e594acdab59a33b419be5ee06391a386f7d285f9669`。
- 新stage：`/home/hxc859/xgap-ch6-artifacts/small48-final39-f1b2583-v1`。
- 预期日志：stage下`small48-final39-<job>.out`。
- 新结果：stage下`continuation/results`；两批旧记录只读。
- 预期归档：`/home/hxc859/xgap-small48-final39-<job>.tar.gz`。

47项定向测试通过（计量/链式恢复36、生成交付脚本11）。实际归档离线检查核验
第一接续561个证据pin及父批179个证据pin，确认177项原记录、39项补集和一处计量
补记。新完整Git bundle已在空目录还原并检查对象完整、无alternates；6个包成员
hash及三段Python编译通过，agent/planner/semantic/LLM算法目录相对f40dfa9未变。

服务器stage先核验两份历史归档及索引文件，读取3891655唯一已终止Slurm记录，
扣除旧1968秒和本次实际Elapsed后，把剩余额度向下取整为分钟；在其中预留900秒
启动/收尾，其余作为研究执行预算。还会在密钥输入和提交前检查完整冻结输入。
密钥输入为空会重新提示；唯一新输出和提交标记防止重复提交。
包生成阶段未提交或产生模型/源调用；提交状态更新见下节。

## 已提交3892875

用户2026-09-27回执确认：服务器还原精确`f1b2583`，prepare成功，隐藏输入密钥
后返回`SUBMISSION 3892875`。本次不重试此前177项，只接续原顺序剩余39项。

- 服务器合同：`/home/hxc859/xgap-ch6-artifacts/small48-final39-f1b2583-v1/continuation/continuation.json`。
- 合同SHA-256：`e33438bc6db3c2cfa7905feffe8346349aa17cbab0a878cdc2c55f362b445ee9`，203,308 bytes。
- 日志：`/home/hxc859/xgap-ch6-artifacts/small48-final39-f1b2583-v1/small48-final39-3892875.out`。
- 预期归档：`/home/hxc859/xgap-small48-final39-3892875.tar.gz`。
- 当前证据为准备/提交成功；作业运行状态、计算节点认证及新结果待收取。
- 无需重新上传或执行stage，不修改已提交版本及冻结输入。
