# Current one-shot development authority

## 当前执行：请求守护与失败计分已接通，继续共同评价接口

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

## 最新执行门限：本轮已完成，暂停至9月13日12:00（北京时间）

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
