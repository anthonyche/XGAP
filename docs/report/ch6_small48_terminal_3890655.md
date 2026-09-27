# 修复后48题作业3890655：终态与接续边界

2026-09-27，Slurm终态来自用户回执；原始归档已回收，938/938份文件大小及SHA-256
一致。下列第一节保留回传事实，后续核验结果补充完整归因。

## 已确认的回传事实

- 源版本：f40dfa9024f1473a90e6f340fb787f90ca204c46。
- 作业：3890655，FAILED，ExitCode 2:0，Elapsed 00:32:48，compt341。
- 研究状态：study_harness_failure；已封存42个方法请求，未封存0。
- 模型调用65次，输入140,424 token，输出21,064 token；unknown_model_usage=false。
- 停止项：D1-test-active-anchor-cycle-000-W1-TS。
- 该项：harness_observation_failure；answer_em=null；guard_status=completed；
  17次模型调用，final_plan_executions=0，source_requests=source_forwarded=52。
- 源观察：harness_response_budget=3；联邦观察：upstream_http_failure=3；
  method_error_type=RetryError。错误的完整正文、请求大小、资源停止证据待原文件核验。
- 相邻window_edge/W1的TS为method_error，8次模型调用、25次源请求；不能仅凭相同
  RetryError推断两者的底层错误相同。
- 片段中的window_edge/W1与active-anchor-cycle/W1内部方法已返回正确答案；这不是
  完整42项的正确率，也不是48题总体结果。

## 原始证据交接

服务器归档：`/home/hxc859/xgap-small48-fixed-3890655.tar.gz`

- 回传大小：2,890,950 bytes。
- 回传SHA-256：`dfd92ed079c0b7793a25855c39f7b31ff5d9e84f1219a02487647ea13e8c4aab`。
- 预期本地位置：`/Users/anthonyche/Downloads/xgap-small48-fixed-3890655.tar.gz`。
- 本次浏览器getState再次30秒超时，用户代下载完成；没有新远程提交或模型调用。
- 本地验收目录：`/Users/anthonyche/xgap-data/outputs/xgap-small48-terminal-3890655-v1`。

## 原始验收结果

| 方法 | 已执行请求 | 正确回答 | 已知失败/截断 | probe次数 |
|---|---:|---:|---|---:|
| XGAP | 10 | 9 | ranked_count/W1提议失败1 | 4 |
| NP | 10 | 9 | 同题提议失败1 | 0 |
| SH | 10 | 9 | 同题提议失败1 | 1 |
| GR | 10 | 9 | 同题提议失败1 | 18 |
| TS | 2 | 0 | 原方法错误1、研究截断1 | 不适用 |

这只是D1的已执行前缀，不能作为三个领域完整结果。40个内部请求中36个答案正确，
没有新增scope拒绝；四次proposal失败来自同一题的相同compact AST。

停止的真正阻断项只有`quiescence_unverified`。lookup首次关闭记录为complete=false、
live_pids=[]、SIGTERM、831.95ms；稍后的external closed.json记录同一PID 3077878
已经回收、returncode=143、group清空。四观察通道均封存、0迟到/落盘失败、用量完整，
最终所有invocation的all_owned_closed=true。源截断为三次超过单响应64MiB上限，
各记录67,108,865字节；这是有界证据前缀，不是可评分完整答案。接续不增大该上限。

共享COUNT失败为模型输出`COUNT(DISTINCT e.xgap_id)`，lowerer拒绝裸技术身份属性。
冻结公共约束已经证明KNOWS边键完整且唯一，但该等价规范化当前只接在后续解释身份
比较，未接在lowering之前。离线使用原公共约束及既有纯函数规范化后可编译为12算子、
4源读取；这不是新增答案实测。本批只迁移资源管理/观察/恢复代码，保持实验算法及
provider配置一致；四个原失败保留，语义入口改进另行版本化。

## 修复和恢复策略

- 退出清理最多等待原属子进程3秒，并在最后一次进程扫描后刷新退出状态；仍要求
  同一进程身份、leader已实际回收、无存活子进程。只改变清理等待，不增大查询预算。
- 预算截断回执明确列出不能接续的gate，不把空live_pids作为成功证明。
- 新恢复合同逐项验证旧terminal/outcome/score/query-loss、全部关闭回执及完整父
  release，生成原顺序未执行补集174项。原42项成功、失败和截断均不重试。
- 代码迁移限定为harness与包装/文档/测试；规划、LLM提议、语义和源请求逻辑不变。
- 累计原65次调用、140424输入/21064输出token。恢复执行最多19632秒，加旧作业
  1968秒为21600秒；明确排除离线人工交接等待，与原绝对日历墙钟策略有区别。
- 新输出目录、独立完整Git bundle、旧归档与938份原证据先核验，再一次提交。尚未
  提交新远程作业；不重启整个48题批次。

本地验收：进程关闭、观察预算、源观察、恢复边界共78项测试通过；生成交付脚本的
成功/未知用量终态及独立包检查另3项通过，合计81项。恢复测试包含真实归档只读
重放、最后一项token未知及未封存阻断、补集顺序、旧成本继承和旧文件不变；没有
真实LLM/后端调用。此验收不宣称剩余174项已执行或语义入口全部无缺陷。

## 已生成的独立恢复包（尚未提交）

- 源提交：`2a8e16e3b03bca4ef075454ef23c9eaff5631e8b`。
- 本地包：`/Users/anthonyche/Downloads/xgapcontinue2a8e16e.zip`，8,548,684 bytes。
- SHA-256：`ec381d0b633782b25d909c7c210a5b7e53b9d1fd9c59ee49d6d37460a69afb91`。
- stage：`/home/hxc859/xgap-ch6-artifacts/small48-continue-2a8e16e-v1`。
- 新结果：stage下`continuation/results`；父目录只读，不重用旧输出。
- 日志：stage下`small48-continue-<job>.out`。
- 归档：`/home/hxc859/xgap-small48-continue-<job>.tar.gz`。
- 8 CPU、24 GiB、无固定节点、无GPU；研究恢复时限19632秒，Slurm上限5小时45分
  包括启动/清理余量。沿用外部API，密钥隐藏输入，启动认证独立计量。
- 空Git目录独立还原、对象完整性、无alternates依赖均已验证；核心agent/planner/
  LLM/semantic及原batch dispatcher相对f40dfa9无变化。旧记录938文件将在服务器
  再核验后才准许准备与提交。离线补集准备通过：42项旧、174项新、5个未完单元。
- 本地证据：`/Users/anthonyche/xgap-data/outputs/xgap-small48-continuation-20260927-v1`。

服务器执行（仅在上传对应包之后；同一stage只允许一次提交）：

```bash
python3 -c 'from pathlib import Path; import hashlib,zipfile; p=Path("/home/hxc859/xgapcontinue2a8e16e.zip"); assert hashlib.sha256(p.read_bytes()).hexdigest()=="ec381d0b633782b25d909c7c210a5b7e53b9d1fd9c59ee49d6d37460a69afb91"; exec(compile(zipfile.ZipFile(str(p)).read("stage.py"),"stage.py","exec"))'
```

## 源码检查发现与待决问题

`scripts/ch6_external_session.py`的预算分类已包含harness_response_budget，且只有
四个观察通道均有封存、无迟到/落盘故障、用量完整、guard完成、quiescence成功时才
允许视为预算截断并接续。短日志没有这些完整字段，因此不能直接把当前结果改成
可安全继续，也不能仅凭category判定分类代码漏写。

`scripts/run_bounded_joint_batch.py`会封存当前项、关闭源，再停止完整性失败；原
输出目录不能换代码，也拒绝带未解决harness失败的直接resume。这些保护保留。

此待决问题已由原始记录关闭：lookup的初次回收确认未通过，其后同一进程已确认
关闭。174项补集已根据完整清单和逐项封存记录计算，179个恢复证据pins已验证。

已封存项（包括方法错误及截断）不得覆盖或自动重试。恢复的累计预算要包含原65次
调用和已报告token，保留新旧代码、配置及冷启动的分界。原始TS输出不修写，不能
把观察层截断计为基线语义错误，也不能把源执行失败隐去。

全量实验与当前48题评价均未完成。新F1–F8为讨论稿，不从此次局部日志外推曲线。
