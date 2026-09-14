# Current one-shot development authority

## 2026-09-14 10:00 北京时间已恢复执行

用户已明确恢复时间为9月14日上午10点，现在继续工程。旧暂停到期；9月15日恢复
是助手对同一指令的误解，已撤销。先完成当前one-shot中间数据生命周期/紧凑trace
里程碑：保留完整最终答案、节点计数与源响应回放，验证共享/并行消费和失败；仅运行
新风险小图与必要真实tiny边界。验收后继续未运行NL group8，新实现epoch记录。
整体Goal保持active，未完成系统/论文评价；不重复旧大题，不优化baseline结果。

以下旧状态为历史；以本节及随后当前里程碑报告为准。

## 当前里程碑：保留策略已通过真实group8；继续冻结顺序的新问题

246f3f0/a23a1fa实现one-shot释放中间行、完整源响应pins、按请求身份安全回放。
13个新风险案例及1个受影响成本检查通过。真实Neo4j+Fuseki tiny4行非空exact、14调用；
保存响应离线重现同计划/答案，零网络/模型/fit/load，首次顺序回放失败原记录保留。
新NL group8（epoch1）两模式各1模型/1最终coordinator，正确空答案，39.199/38.261s，
10源请求88284870B，方法RSS0.806/0.828GB；完整core trace207631/207615B。
FedUP原生失败EM0，FedX共同响应预算中断EM0；四方法共12132输入/2195输出token。
这是不同问题，不把它和group7算作提速对照。当前仍缺完整非空NL/总体/scale结果。
[完整报告与逐项证据](report/one_shot_retention_20260914.md)。唯一equality-v1 NL journal
现在下一group9（已保留前36结果），下一chunk继续原顺序；Native fixed20、RDF fixed5。
所有本轮服务/句柄终态，原预算/基线/统计/模型不改。整体Goal active，用户已明确恢复。

以下为历史结果，未实现/暂停等旧时态不代表本轮状态。

## 2026-09-13 最新执行状态

[冻结键上界与真实新组结果](report/equality_key_bounds_20260913.md)、[Goal顶部](goal.md)为
当前交接。16新风险案例及1个真实tiny普通入口通过；完整源id上界已冻结，模型自行选fanout。
新真实NL group7两模式正确空答案，80.876/84.423s；4模型调用，所有服务终态。
下一tiny门为中间rows生命周期/紧凑trace（尚未实现），然后新equality journal未运行group8。
Native fixed下一20、RDF fixed下一5；旧暂停已解除，整体Goal/论文评价尚未完成。

## 当前执行：共同固定语义入口已验收，先修正 RDF 表示重叠

用户已于9月13日13:32提前恢复工程和实验，旧暂停解除，heartbeat按小时推进。
1db4c3a接通schema-only源分配、共同结果评分、完整外层计时、worker+方法host/数据库
资源观察和失败后自有进程组清理。6项新风险检查通过；一次tiny共同入口三方法各
执行一次，XGAP金额66/9 exact，FedX金额8448/1152（128倍），FedUP聚合HTTP500。
共171次源请求；零模型/fit/probe/retry/算法修改；服务全部已停。
[完整结果与边界](report/common_rdf_trial_20260913.md)。

发现我们两源RDF表示有24条重复身份/类型事实；本地集合并集诊断返回66/9，
与FedX的重复匹配放大有明确语义混淆。不能把这个问题当作XGAP planner优势。
下一步版本化共同规范事实，使其跨源互斥，并保留本地元数据映射；只修正我们的
共同输入，不修改baseline算法/答案，不按方法结果挑样本，旧表示与原结果保留。
随后完成共享NL前端→外部全局查询编译，以及完整服务装载/平衡campaign控制。
固定语义不是NL E2E；当前外部共享NL接线尚未实现，不能宣称系统评价已完整就绪。

开发继续tiny/failure replay，不重跑旧成功门禁、不重训时间回归。120组与评价33空/
15非空冻结，campaign_ready=false。Sep14 17:00核心/接口和Sep18真实实验目标保持。

## 以下为历史交接，以当前执行为准

## 历史暂停交接：9月13日13:32已由用户提前恢复

用户最新指令：本轮完成并汇报后暂停，**2026-09-14 12:00 Asia/Shanghai
（04:00 UTC）恢复**。本节覆盖全部旧继续、小时推进或暂停指令；到时之前不启动开发、
测试、模型/数据库/训练、baseline或远程轮询。整体Goal仍active且未完成，不误记为
complete/blocked。原heartbeat已改为中午恢复，到时才接续并恢复小时推进。

f385709已接通独立RDF端点配置和冻结估计器投影。5项新风险检查首次全过0.47秒；
一次8实体/16关系真实双Fuseki gate，三类查询各只执行一个预选计划，全部独立答案
exact，graph/control共16次必要调用。零模型/baseline/fit/probe/retry；复用原数据和
原32条训练权重，输入封存不变，两个服务和进程组均已退出。
[完整进展、结果与限制](report/rdf_instances_native_20260913.md)。

本轮证明同事实RDF确定性链已实际接通，不证明总体NL准确率、排序最优、提速或scale。
新实例迁移未校准；完整SF0.1 RDF profile尚未发布，完整服务尚未装载，campaign_ready=false。
先前普通NL+真实双库成功、完整serving输入/catalog、120组population和worker守护继续
接受，不重跑成功门禁，不重建catalog，不为毫秒误差重训。评价33空/15非空保留。

明日恢复后先补共同外部输入/规范化评分、完整外层计时、托管服务资源和异常后静止
屏障，再发布完整RDF配置并按已批准协议运行FinBench native/RDF/FedUP/FedX，之后
有界FedShop，消融最后。baseline只需忠实可运行、如实反映结果，不替它优化。
Sep14 17:00核心/接口和Sep18真实实验目标保持；恢复后距前者仅5小时，优先必要接线。

## 以下为历史安排，以上方最新门限为准

## 前序：请求守护与失败计分已接通

017a0d2新增180秒独立worker守护、采样RSS/日志/进程预算、进程组清理与失败终态。
5项新风险检查一次通过0.82秒；一次完整FinBench profile零调用预检通过，worker
2.872秒、采样RSS238.922MiB。中断题保留身份和分母，失败对空gold计0；部分用量
未知即保留unknown。没有模型/数据库/训练/方法运行或旧成功门禁重跑。
[本轮证据与准确边界](report/one_shot_process_guard_20260913.md)。

此前真实serving输入已冻结（161ef2e）：18表55,604实体309,577关系，59,587条catalog，
原model未fit，新source统计与两模式可加载；[输入证据](report/finbench_serving_profile_20260913.md)。
服务尚未装载执行，120题及33空/15非空评价分母不变。当前守护只覆盖方法worker，
父adapter完整成本、常驻server/数据库资源和异常后的静止屏障仍需共同runner接线。
下一步真正连接XGAP-RDF多endpoint的compiler/estimator身份、共同外部输入/评分，
再真实主评价/scale，最后消融；不替baseline优化结果，不继续反复做catalog。
用户暂停已到期，heartbeat按小时推进；整体Goal未完成，Sep14 17:00/真实Sep18保持。

## 历史暂停记录：截至9月13日12:00（已到期）

用户最新要求：完成本轮milestone、汇报后暂停，**2026-09-13 12:00 Asia/Shanghai
（04:00 UTC）恢复**。本节覆盖下方所有旧“继续/下一步/每小时推进”指令；期间不启动
下一轮开发、实验、模型/数据库调用、训练、baseline或远程轮询。Goal整体尚未完成，
保留active目标，不将暂停误记为complete/blocked。

真实FinBench SF0.1新120组已由49aaff0代码一次离线构建并核验，24开发/48训练/48评价，
每类40；NL、独立CSV答案与gold隔离，361个文件校验值通过，旧锚点/近重复与跨split
组复用检查通过。耗时5.400秒，零模型/数据库/fit/方法运行。评价组33空/15非空，
直接转账组40题全空；必须分组报告，不能重抽题改善结果或只用总体EM讲准确性。
[本轮进展与边界](report/finbench_one_shot_population_20260912.md)。

恢复后才准备真实serving profile/catalog/statistics、同事实RDF和共同评分/资源预算；
正式campaign_ready仍false。核心已通过的NL→估计选择→真实双库答案继续接受，不重跑。
外部baseline只保证忠实可运行、如实报结果。Sep14 17:00/Sep18目标保持。

## 以下为前序进展，执行时间受上方最新门限约束

紧凑意图确定性编译、冻结catalog预测绑定、六个合法计划按估计选一个，执行Neo4j6次+
Fuseki3次，答案账户2=66、账户3=9，与独立reference完全一致。核心在线3374.613ms；
零probe/训练/fit/retry/baseline调用，服务已停止、输入封存未变。[完整证据](report/compact_financial_nl_20260912.md)。
六项新provider/录制/模式/模型兼容检查通过；未重复此前九项lowerer检查或旧成功门禁。
该结果是一个曝光开发题的performance集成证据，不是完整金融NL准确率或baseline提速。
路径/风险排名有独立小图和冻结估计证据，实际compact模型质量待正式评价。旧v1/v2/v3
[失败与成本](report/financial_nl_20260912.md)原样保留，不调prompt修该题，不替baseline修结果。
下一步冻结批准的真实FinBench/RDF样本、独立reference、数值等价和预算/split契约，
补必要共同输入适配后执行主评价；消融在后。Sep14 17:00核心、Sep18真实结果目标不变，Goal active。

# Approved 48-hour core integration plan

Authority: user approval and instruction to update Goal/docs and execute,
2026-09-12, Asia/Shanghai. Start 2026-09-12 17:00; core acceptance target
2026-09-14 17:00. Real-evaluation deadline remains 2026-09-18. These are delivery
targets, not claims that performance advantages or all experiments are complete.
The [one-shot contract](decisions/one_shot_modes_v1.md) governs this work.

Estimator acceptance update from the user: useful relative plan ranking is an
allowed target; precise runtime regression is optional. Retain the accepted v2
implementation and prioritize the split-source/NL-only boundary, not lower fitting
error. Any future rank-only output needs explicit units and joint quality-selection
semantics. This adds no training, regression run or deadline extension. Later
evaluation will assess ordering and plan-selection regret, with offline references.

| Beijing time | Milestone and acceptance |
|---|---|
| Sep12 17:00–21:00 | Freeze semantics/modes/one-shot/strategy/cost contracts; update authority; begin implementations. |
| Sep12 21:00–Sep13 09:00 | Parallel bounded top-K frontdoor, real legal strategy DAGs, runtime-plan frozen estimator adapter. |
| Sep13 09:00–17:00 | Connect joint selection and one final execution to ordinary NL entry; tiny NL-to-answer slice must work. |
| Sep13 17:00–Sep14 05:00 | Actual precision/performance budgets and approximation/terminal semantics; no compulsory user loop. |
| Sep14 05:00–13:00 | Only affected module checks and necessary tiny real LLM + Neo4j/Fuseki boundary verification; preserve failed attempts. |
| Sep14 13:00–17:00 | Freeze implementation, run contract and evaluation interface; report evidence/remaining limits and discuss 16–20-figure plan. |

## Current milestone / ownership

The [bounded-core audit](report/one_shot_core_freeze_20260912.md) is complete. Actual
split-source ordinary NL-only evidence remains accepted. The reusable frozen
profile/request/result interface and independent post-seal scorer are implemented;
nine unique new-risk cases pass plus one zero-call CLI preflight. No new model or
backend runs, fitting or accepted-gate repetitions occurred for this wrapper.

The implementation can now support experiment-plan discussion. The [18-figure
draft](research_experiment_proposal_20260912.md) is prepared with RQ/X/Y/population/
costs and primary-source-verified external candidates. The user approved its dataset priority.
Freeze concrete samples/artifacts/budgets and finish thin adapters before campaigns;
do not repeat the priority approval question.
Benchmark-specific profiles/references/adapters and cohort aggregation are still
required. Current estimator v2 is retained: relative ranking is a sufficient goal,
accurate time regression and rank-only implementation are not completion gates.
TheSep14/Sep18 targets remain; the overall Goal remains active.

## Earlier milestone / ownership history

At 41a3cca the first guided real B01 precision answer is accepted: one model call,
one selected plan, two Fuseki calls, independent gold exact. Current-query probes
and new training/fit are zero. This succeeds ahead of the ordinary mechanical
target, but core acceptance is still open for operator/backend-aware estimator
features and independent training coverage, necessary cross-store execution,
and an unaided NL-only/performance request. The actual cost prediction is severely
low and cannot support a performance claim. [Latest evidence](report/one_shot_native_20260912.md).

Initial implementation checkpoint was 793cc1d3e94b98bd669bd93af8346b3583c88a65.
Root owns Goal/docs, mode contract, ordinary request orchestration, joint selection
and final integration. Parallel bounded tasks own candidate interpretation,
physical-strategy compilation, and the frozen runtime estimator respectively.

Allowed: corresponding semantic/LLM/runtime/planning/agent modules, small affected
tests and current design/status documents. Forbidden: altering synced sources,
old gold, cohort IDs, exposure labels, archived outputs, secret persistence,
large-data development runs, new comparative experiments or unneeded product work.

Acceptance is staged: code exists; targeted mechanics checked; ordinary tiny E2E
checked; real external boundaries checked. Keep these states separate. Completion
requires the ordinary entry, not merely separate experiment runners or new APIs.
Targeted tests address new failure risks, not every historical milestone again.

No new expensive runs are authorized by a calendar checkpoint alone. No changes
to remote3804210; user will supply updates. External LLM availability is established.
The existing hourly development heartbeat may resume under this approved scope;
notify only meaningful progress, completion, failure or required user action.

## First execution checkpoint

The shared ordinary-entry tiny slice and initial three adapters are now implemented
and checked; see [report](report/one_shot_core_20260912.md).48 new risk cases pass,
including the two controlled modes with independent B01 answers. This advances
the ordinary-entry mechanical gate ahead of the24-hour target; actual external
LLM/Neo4j/Fuseki verification remains outstanding. Keep the dated remaining gates
and do not substitute these checks for real model or performance evidence.

## First actual native attempt

Checkpoint b008775 started and loaded both actual stores, completed four
independent tiny training measurements, and froze/reloaded the fitted estimator.
The one external B01 request returned a malformed parameter structure; binding
rejected it before planning or final execution. All four catalog resolutions
succeeded. See the retained [failure report](report/one_shot_native_20260912.md).
The real NL-to-answer gate is open; this failure is not a backend answer error.

The next change shares typed parameters between the candidate wire schema and
admission. Replay the saved failure locally and retain its original status.
The native harness now supports reuse of the accepted frozen estimator; a new
protocol gate must use it, with zero new training/fit calls. Historical training
costs remain separate from current reload and query costs. Do not repeat accepted
module gates or the four training executions.

The typed contract and five new checks are now accepted. A separate bc4103c
native attempt reused the model with zero training/fit but received HTTP 500
before interpretation. The real answer gate remains open. The next task is an
explicit provider wire compatibility profile retaining identical local admission;
HTTP 500 alone does not identify the root cause. No automatic request fallback.

Input-profile acceptance also distinguishes the current guided request (original
NL plus declared output fields/prepared hard constraints) from unaided NL-only
Interpretation. After this boundary works, verify one small ordinary NL-only
request without prepared operator IDs/constraints; preserve the guided gate's
scope and do not treat it as an independent model-accuracy evaluation.
