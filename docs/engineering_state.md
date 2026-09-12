# XGAP current engineering loop

紧凑图意图schema与确定性编译器已实现：自动分配中间列、派生属性读取、强制共享
变量相等，保留平行边并支持显式去重。三类独立金融intent在分开的本地RDF事实上均
得到预期答案，九项不同的新风险检查通过；ACYCLIC沿用“节点不重复”的原代数含义。
[本轮证据及边界](report/compact_lowering_20260912.md)；[契约](decisions/compact_financial_interpretation_v1.md)。
本轮零模型/native服务/baseline/训练调用。紧凑provider与普通NL入口接线仍待完成，
下一步完成该接线、检查既有预算/冻结模型兼容性，再做一次必要tiny真实NL边界。
金融NL v1/v2/v3仍均未得最终答案，[失败与成本](report/financial_nl_20260912.md)原样保留。
不继续逐题prompt调优、不重跑旧门禁、不替baseline修结果。两模式、Ptime选择与一次
最终执行不变；Sep14 17:00核心、Sep18真实结果目标保持，Goal active。

前序输入证据：FinBench同事实离线映射已实现；8实体/16关系小图上的三类查询
在真实Fuseki各执行一次，独立答案均exact。该轮没有LLM、baseline、训练或大数据调用。
当时缺失的边属性访问和字段/时间比较现已实现并完成上方确定性双库验证；金融NL待验收。
[前序结果](report/finbench_rdf_tiny_20260912.md)；[表示契约](decisions/finbench_same_facts_rdf_v1.md)。

最新原则：baseline只要能运行并如实记录，不替它修算法、补语义或优化成绩。
FedUP/FedX已在双源9事实tiny图运行；FedUP排序错误、聚合失败保留，不是待修复门禁。
外层Jena补全尝试已撤出；后续工作回到XGAP的FinBench输入/reference与正式评价准备。
[接入结果与成本](report/external_federation_tiny_20260912.md)；[baseline原则](decisions/baseline_fidelity_v1.md)。

## Current: bounded core and reusable record interface ready for experiment discussion

The [requirement-to-evidence audit](report/one_shot_core_freeze_20260912.md) separates
implemented functionality, controlled/replayed checks, actual native evidence and
unmeasured research claims. The ordinary split-source NL-only actual answer remains
accepted at6833e19/f0d88d3. Do not repeat it, its six checks or28-plan training.

The new generic profile/record/scoring CLI has nine unique new-risk cases passing
and one zero-call CLI preflight. It reuses the accepted model/provider and saved
success/failure without new model/database executions. Source/mode/file/prompt
identity drift fails explicitly; known usage survives a failed result seal. New
replay records are engineering evidence and must not enter live timing aggregates.

The [18-figure discussion proposal](research_experiment_proposal_20260912.md) and
[external comparator evidence](report/external_comparators_20260912.md) are now
prepared. All18 RQ/X/Y/comparator rows and local links passed document consistency
checks. No software tests, model/native runs or fitting were repeated. FedUP/FedX
are appropriate RDF comparators; KBQA-R1 has2026 paper/model-card evidence but is
not locally deployed. Four direct repository metadata calls failed URLError; no
commit SHA is verified, no automatic retry occurred, and no process remains live.

User approved the recommended priority in the async reply: FinBench native plus
matched-RDF FedUP/FedX first, then bounded FedShop; retain GrailQA/KBQA-R1 without
blocking the first tracks. Do not ask for this approval again. The manifest now
records priority_approved_protocol_finalization, authorization true, campaign_ready
false. Next pin the external implementation/dependencies and build the thin adapter,
then freeze dataset/reference/sample/budget manifests and pass necessary tiny
boundaries before formal runs. Core tests and native successes remain accepted.
Sep14 17:00/Sep18 and remote3804210 ownership are unchanged.

Estimator priority remains relative plan selection, not precise ms regression.
The existing v2 returns ms; no rank-only adapter or ranking benefit is claimed.
Do not fit or collect more labels just to reduce time error.

## Earlier: v2 estimator and excluded cross-backend deterministic request accepted

Checkpoint a2c1908 completed the declared 28-plan independent tiny collection
(46 backend calls, two separate warmups), offline nonnegative fit/freeze, and one
excluded ordinary performance request. The answer is independently exact, with
one selected coordinator plan, Path on Neo4j and Match on Fuseki, two final calls,
zero LLM/observation/online-fit calls. Predicted execution 9.524 ms versus actual
18.695 ms is one within-family excluded point, not a ranking or speedup result.
Five new checks passed; all 434 input fingerprints and the previous model match.
Owned services stopped. [Evidence](report/work_estimator_native_20260912.md).

Do not repeat these 28 training executions, five checks or the accepted request.
Reuse the new model only with its admitted source/snapshot identities. Work proxies
remain coarse; missing selectivity and category coverage are explicit. Historical
v1 and B01 evidence stay intact. V2 model path:
`/Users/anthonyche/xgap-data/work-estimator-v2-native-20260912-a2c1908/frozen_work_estimator.json`.

Next core gate: a tiny split-source fixture requiring contributions from both
Neo4j and Fuseki, plus an ordinary NL-only request without predeclared operator
IDs/structured constraints. Real cross-backend mechanics have now passed, but
current data are replicas and this gate's semantic input was declared. Keep those
limits visible. No new comparative/big-data campaigns before core acceptance.

## Earlier milestone: first guided external one-shot answer accepted

The code is committed through 41a3cca. Both modes share the controlled ordinary
entry; B01 precision now completes one actual external request and one selected
entity-bind execution with the exact independent answer. Two final query calls
both use Fuseki. No current-query observations, training or automatic retry were
used. Retain this accepted slice and all prior failed attempts; do not rerun the
64 accepted targeted checks. [Evidence](report/one_shot_native_20260912.md).

The earlier bounded task list was (superseded by the latest checkpoint above):

1. Represent operator/backend/workload associations in estimator features, then add
   independent tiny training coverage for physical strategies, placements and runtime
   shapes, with visible extrapolation behavior. More samples alone cannot distinguish
   swapped backend assignments that currently produce identical feature vectors.
   The four Match-only samples gave an unusably low selected estimate (0.0054 ms
   versus about 78.93 ms actual); do not train on the accepted B01 request.
2. Maintain a separate tiny two-source fixture where Neo4j and Fuseki each supply
   a necessary subquery. The current replicated fixture permits all-Fuseki execution
   and therefore does not verify cross-store behavior in the new ordinary entry.
3. Verify one NL-only/performance request without prepared operator IDs/structured
   constraints. The accepted B01 gate has declared hard request/output inputs;
   preserve that exposure boundary and do not call it unaided interpretation.

Each task needs only its new-risk checks and one necessary tiny slice. Use the
explicit envelope-schema-v1 provider profile (wire/local schemas remain separate)
for the established endpoint; do not retry the previous HTTP500/empty-object
requests or silently change profile after failure. Catalog and measured training
stay offline/frozen, with separate costs. No large-data or comparative campaigns.

Goal remains active under the approved Sep14 17:00 / Sep18 targets. Remote3804210
remains user-managed. Credentials stay out of files and automation prompts.

## Historical preparation checkpoint (superseded by the actual attempts above)

Checkpoint54144e9 contains the accepted first ordinary slice. The mode-matched
external provider, one-question durable recording/replay and endpoint CLI are
now prepared;5 additional new harness-risk cases pass. Default operation is
zero-call preflight. Original B01/B04 request text is separate from post-seal
gold access; execution success and answer exactness are separate fields.

The owned tiny native gate also passes its first zero-call preflight: four
independent generic Match plans compile; source snapshot/catalog/request budget
match. It reuses cached Neo4j5.26.30/Fuseki5.6.0 and Java21. With explicit execution
it will measure those four training plans once, freeze/reload the model, invoke
one B01 model request and execute at most one final selected plan. Preparation,
training and online/post-return costs are separate. This will be a new-profile
integration gate, not a benchmark campaign or estimator-quality experiment.

No native/model action has yet occurred for these new harnesses. Do not repeat
accepted module checks or preflight; next review/freeze code and perform this
single new external gate, preserving terminal failures and stopping owned services.

## Accepted first slice; next new-profile tiny external boundary

Root and three bounded tasks implemented the shared entry, modes, candidate pool,
predicted grounding, true strategy neighborhood and frozen ridge adapter.48 new
checks now have passing terminal results (10candidate+9grounding+8strategy+
10estimator+11ordinary-entry). Root10 first0.61s, then only1 new cap check0.24s;
no live/native/large benchmark call. [Detailed evidence](report/one_shot_core_20260912.md).
Prior tests are accepted; do not rerun them absent new risk. The next bounded work
prepares a mode-matched provider/frozen model for one ordinary tiny real external
gate. Current model labels are analytic toy and do not prove real accuracy or
latency prediction. Keep source/version identities exact and all one-time costs.

## Current execution — user-approved resumption on2026-09-12

M1 of [48-hour core integration](one_shot_development_20260912.md) is active.
Start checkpoint793cc1d, initially clean. Root owns mode/ordinary entry and docs;
three parallel bounded implementation tasks own top-K interpretation, executable
physical strategies and frozen RuntimePlan estimator. No new native/model run or
comparison has been performed for this milestone yet. Record first focused tests
and integration results here as they occur; do not infer acceptance from code.

New authority: [one-shot modes v1](decisions/one_shot_modes_v1.md). Existing
FinBench raw evidence and all old gates remain accepted and unchanged. No need
to rerun them. The prior discussion pause below is superseded by explicit approval.

## Historical execution checkpoints

## Latest E2 — full original48 completed; paused for user discussion

Read [balanced result](report/finbench_paid_balanced_20260912.md). Parent9d8cf2e
plus fingerprinted native/journal changes:12 focused checks first pass0.66s;
one native session91544 exit0,95.585s.864 final+576 acquisition exact,2880 query
calls,0 model calls; six method-permutation blocks, original32seen/16heldout and
three exposed IDs retained. Online persistence measured and charged; full seals
separately13.814s.362 source/input fingerprints unchanged. PID73063/PID73129 stopped
and independently absent; owned state removed. No live native process remains.

Raw /Users/anthonyche/xgap-data/e2-finbench-balanced-20260912/ includes frozen
orders,96 prepared plans,sealed six-block outcomes,once post-seal evaluation,
analysis and audits. First analyzer run exit0 in7.540s.102 artifact-only checks
pass. Primary paid/hash3.262 [3.188,3.334], paid/bind2.601 [2.550,2.652]; no total
cost benefit. Heldout16 descriptive1.846/4.650. Not P1/A3, LLM or scalability.

USER PAUSE: after this round, report and discuss improvements; heartbeat is paused.
Do not start the proposed real strategy/P1/A3/forecast work or rerun accepted gates.
LINK remains3/5; GrailQA150 remainsnot_run;3804210 untouched pending user updates.
Historical next-step entries below are superseded by this checkpoint and pause.

## Latest E2 — real15/15 plan correctness; growing-ledger timing confound recorded

Read [the paid-selection pilot](report/finbench_paid_pilot_20260912.md). Parent
0f741fb plus fingerprinted core/native driver:12+2 focused checks passed first
run0.55/0.19s. Native session20774 ran once, exit0,37.27s;9 final+6 acquisition
exact,30 query calls,0 model calls. All48 IDs/32seen/16heldout retained; selected
f1-01/f2-01/f3-01 stay integration-exposed,45 not_attempted.23 artifact-only
checks pass,361 inputs/source hashes unchanged; PIDs66620/66664 verified absent.

Raw /Users/anthonyche/xgap-data/e2-finbench-paid-pilot-20260912/ retains orders,
plans sealed before dispatch, raw client journals, sealed execution before gold,
full evaluation and cleanup. Do not repeat this pilot or the14 checks.
Method wall is unsuitable for formal comparison: each progress update rewrites
the cumulative full ledger (5.8MB final), and method/cache order is not balanced
within query. Next persist each new action once plus a small index, measure
persistence explicitly without subtracting guessed old overhead, and freeze
original48 repeated balanced blocks. This is a prepared-plan baseline, not P1/A3.
LINK3/5 and every historical failure remain;3804210 is untouched.

## Latest LINK — three exact native answers, complete five-question denominator

Read [Match/cohort evidence](report/match_row_link_20260912.md) first. Match named
row predicates compile to the existing post-normalization Filter, preserving
typed semantics and raw constraints.10 compiler+7 cohort checks passed first run;
do not rerun. One native session55092 exited1 because the cohort is3correct/5,
not all-correct: B01/B04/B05 exact; B02/B03 Interpretation invalid beforebackend.
All five terminal; no new model calls.15 query calls=10 observations+5 executions.
Raw /Users/anthonyche/xgap-data/match-row-link-20260912/ contains source/recording
hashes, actual rows and cleanup: PIDs62798/62840 stopped and verified absent.
B01 uses Fuseki paths+Neo4j Match; B04/B05 selected Fuseki. No candidate/reference/
old-slice reruns. Current interface is usable; model quality remains imperfect.
Next implement real E2 via finbench_paid_selection_pilot_v1.md, not repeated
five-question prompt tuning. Historical v2/32B failures and original150/48 stay.

## Latest external LINK — serving connected; exact output shape remains open

Read [external LINK evidence](report/external_toy_link_20260911.md) first. The
user-authorized retry returned200and a valid schema probe. Explicit external toy
binding is implemented;18new+1legacy tests passed, then only1new ledger test after
the recording-failure correction. Five actual responses pass parsing,5calls and
12058tokens. Native session14277 exited1: B01 agent/P1 execution succeeds with
Fuseki paths + Neo4j people,4observations+2executions, but exact gold excludes its
extra age column. Do not silently drop it. B02–B05 were not run natively. Owned
services stopped successfully. Reuse /Users/anthonyche/xgap-data/external-toy-wiring-20260911/;
no repeat generation/native failure. Next local projection-contract diagnosis,
then the remaining actual LINK and fair real-data experiments.3804210 untouched.

## Current E1-B/INT-5 checkpoint — scoring accepted; existing facts recovered

Parent72aeea7. Independent entity_answer_evaluation.py consumes E1-A runs and
normalized evaluation references, with exact population/method/terminal/identity
checks. Full-cohort EM/F1 waits for complete compatible records; failed empty is
not correct empty, unknown costs remain unknown.18 new checks pass first run0.45s
(process0.984s,tool ee7bca exit0), hashes unchanged. One controlled E1-A→score
slice, no old test/native/model rerun. Original150 reference format was checked
once, with all150 explicitly not_run and no accuracy. See
[report](report/entity_answer_evaluation_20260911.md).

D201's previously overlooked first-shard files still existed. Their24files,
436,303,952bytes were copied once to
/Users/anthonyche/xgap-data/int5-freebase-first-shard-20260911/original/;13facts
parts/parquet/manifests match frozen hashes. Source is query-independent but1/964,
not full GrailQA. HistoricalD202 load receipts/state exist; current DB usability
is not verified and no service started. Do not rebuild/recover these same inputs.
Next adequate real-data coverage, measured inference, actual prior forecast/cost
and fair E1–E5.3804210 remains user-observed PENDING(Resources), user will notify.
All later missing-facts/current-state claims are historical; no local handles.

## Current milestone — real FinBench integration passed; model LINK failure localized

Both supplied archives are verified and available locally. Real FinBench SF0.1
facts pass the fixed original3-query/6-plan correctness gate and107/107 independent
audit; whole SF0.1 was loaded, original48 kept, no model or ordinary-P1 experiment.
All owned services are stopped. See [INT-3 evidence](report/finbench_original_three_native_20260911.md).

Actual Qwen3804011 completed5 calls/10484tokens, but unchanged ordinary-entry replay
completes0/5, all before backend access. Four reference undeclared source slots;
B04 first fails scalar resolution and also has invalid source assignment. The
parser now rejects malformed/undeclared/source-misplaced references before any
resolution.21focused cases and five original-response admission replays pass;
these are rejection checks, not repaired answers. Promptv2 is prepared with unchanged
questions/context/hard requirements; tokenizer preflight and fresh model quality
are unmeasured. See [LINK failure and correction](report/qwen_model_link_failure_20260911.md).

Next:one bounded v2 model diagnostic after source transfer/preflight, real prior
forecast/cost preparation, gold-blind GrailQA answer projection and fair frozen
E1–E5. Do not repeat accepted INT/native/module gates or ask for already recovered
archives. Runtime exchange bytes are serialized EXCHANGE rows, not wire traffic.
All old unreceived/PENDING/unknown statements below are historical. Deadline and
GrailQA150/FinBench32seen+16cold populations remain unchanged.

## Current A4 gate — accepted; external inputs still pending

Offline empirical preparation, exact profile provenance and current environment
binding are implemented through the ordinary query entry. Eighteen unique new
cases and one affected legacy case have passing evidence. The final 19-case run
passed18/failed1 in0.64s due only to a new test reading successful output on an
agent failure; its corrected assertion passes alone in0.40s. Refresh reselection
and common scoring are separately timed, without changing their total.
See [A4 evidence](report/semantic_forecast_preparation_20260911.md).

The 21-file/64-MiB original FinBench workpack collector has seven standalone tiny
tests passing. A checked ZIP and Chinese one-step handoff are in XGAP-deliverables.
It has not run remotely;3804011 remains last-confirmed PENDING. SSH config absent
locally and previous browser access failed; no automatic external retry. Real
facts/load/workpack/model artifacts remain the necessary next external inputs.
No actual training forecast is frozen: old A1 records lack a declared prior phase
and pure reselection cost and must not be relabeled. No new native/model/full
regression or large-data run. Preserve the original150/48 evaluation denominators,
all failures, September18 deadline and the research-plan acceptance ladder.

## Current INT-1 gate — accepted; real artifacts/answers next

See [INT-1 evidence](report/resource_triple_encoding_20260911.md) and current
status/roadmap. P1/A1/A2/A3 are accepted within their stated bounds; their old
next-action text below is historical. INT-0 restored7 original GrailQA files;
INT-1 now connects raw resource triples/Neo4j mirror to ordinary PathSet/P1.
28 unique new and3 affected checks have passing evidence; native67378 exit0,
ten query outcomes match independent gold (12 calls including loads),334 source
hashes match, both owned services stopped. Do not rerun these unchanged gates.

Next actual work: real query-independent facts/load receipts, original FinBench
workpack and independent answers/forecast inputs. Scalar comparisons are outside
this new resource adapter (legacy scalar execution code exists); preserve their
10 frozen pilot IDs and outcomes rather than shrink150. The two fixed real inputs
compile4/4 but actual answers remain unmeasured. Remote3804011 still has no newer
confirmed state; the previous user status request remains pending.

## Current A1 gate — accepted, residual execution bridge next

Parentd66bd84 plus the accompanying A1 source receipt implements SemanticRefreshPolicy
and run_semantic_plans ordinary-entry forwarding. Modes refresh_reselect,
refresh_only,no_refresh require the same complete warm table, choose one initial
plan key using historical elapsed estimates, keep memory read-only and optionally
reselect once. History/certificates/current costs retain separate provenance.
See [A1 evidence](report/semantic_refresh_20260911.md).

All local handles terminal:49192 existing memory/static60pass/4.01s; new refresh
11pass/0.71s and additional failure-retention1pass/0.16s. Default interpreter first
had1pass/10skip from unavailable RDFLib; pinned venv verified actual cases.
Native97715 exit0: B04 cold prep+three arms,2 references and retained slice,
12 validation query calls excluding setup. Raw
`/Users/anthonyche/xgap-data/a1-refresh-native-20260911/result.json`;
40/40 source hashes match; Fuseki10831 andNeo4j10801 stopped normally. No broad,
large-data or model calls. All three native arms correct, selected Fuseki/Neo4j/
Neo4j, current calls2/2/1, observed question time28.73/42.10/14.98ms. Synthetic old
cardinality/latency table is explicit; current native reports unmodified. This is
not a natural-drift or speedup experiment; no-refresh was fastest.

Next actual integration gap: execution-prefix adaptation over the P1 local-option
space. Existing AdaptiveFederatedExecutor expects explicit candidates/common
probe definitions; scheduler initial_results alone does not establish safe reuse
across changed replica definitions. Freeze executed placements and exact reusable
node/ancestor identity, define residual feasible-domain/cost and bounds, then use
existing probe/observation/scheduler primitives. Tiny changed-remaining-placement
case + no-replan, independent gold and no duplicate prefix calls. Do not rename
A1 as full runtime adaptation. Acquisition stopping/value policy also remains;
new LINK/INT/E1–E5 evidence still needed. No additional framework expansion.

Remote3804011 remains only user-observed PENDING, prior ETA18:28 Beijing9/11;
no new query/submission/browser retry in A1. Full Goal active, September18 deadline,
toy-first development and no automatic external retries unchanged. Two bounded
collaborators provided proof/API review and new focused tests; no delegated
external actions. Root owns source integration and live gate.


Updated: 2026-09-11. Owner: task 01a085a5-3722-78e2-aab8-c19ef093c36d.

## Current P1 implementation — scoped correction accepted

Parent6ed9cce's terminal-source counterexample is saved explicitly and corrected.
The ordinary selector requires invariant rows/width only for consumed sources,
computed from all semantic input IDs. Guards for topology, source dependencies
and independent budget feasibility remain. Final29 P1 tests pass in0.72s
(session72605 exit0). Scope and evidence:
[terminal-source correction](report/polynomial_terminal_correction_20260911.md).

150 affected model runs completed;70 reused oracle values all matched,73 costs
improved, at most2 full-plan scores plus K local scores. Do not repeat fixed-row
150 or exhaustive work. Replay74295 exited1 only on an overly strict native
selection-diagnostic assertion after all model cells passed: B04 is terminal and
its certificate correctly becomes exact. The final replay reused those cells;
all10 native plans/primary costs identical,8 selection records identical,2 B04
certificates improved. No new backend calls. Raw final result is
`/Users/anthonyche/xgap-data/p1-terminal-replay-20260911-final/result.json`.
All local handles are terminal. No broad suite or remote action in this step.

Next concrete gate: thread a one-request warm-snapshot profile refresh and
optional pre-execution reselection through run_semantic_plans and the ordinary
query tool. Reuse PlanObservationCollector.collect, snapshot.with_estimates and
space.select. Same complete history/B04 gold for refresh+reselect, no-reselect,
and no-refresh arms; J=1, one reselection, complete current/historical cost,
terminal failure without retry. This is not execution-prefix adaptation. Older
adaptive executor exists but requires explicit candidates/identical probe nodes;
residual feasibility and exact reuse across placements need a separate contract.

Real-model3804011 still only user-observed PENDING; ETA9/11 18:28 Beijing is an
estimate, not a live-state check. No poll/resubmit/browser retry performed. Full
Goal remains unfinished; keep September18 deadline and tiny-data development.
One read-only collaborator reviewed the proof and next API gap; it made no edits,
ran no tests and performed no external calls.

## Preceding research-directed priority — R0 plan, then P1

The user requires all engineering to serve explicit research questions and
experiments, with X/Y factors for effectiveness, efficiency and scalability.
See [the experiment plan](research_experiment_plan_20260911.md) and
[Ptime planning contract](decisions/planning_ptime_contract_v1.md). Current main
placement generation is exponential when its rejection cap is removed; P1 is an
actual implementation gap, not merely missing tests. The proposed exact subcase
and conditional heuristic certificates have not yet replaced that implementation.

T3-B is accepted at7aad1dc:148 focused; real-native5 cold+5 warm programs/18
candidate answers/10 references+slice; full90283 terminal0:3481/38,691.20s,24
entrypoints. Do not poll or repeat completed handles. The broad run had finished
when the latest instruction arrived; no new regression was launched for R0.
All further gates must follow the experiment plan; a milestone alone no longer
triggers a broad suite. R0 changes only design/priority documents, not runtime,
frozen experiment data/protocols, or remote submissions.

Next implement P1 using local alternatives, explicit feasibility, fixed-pass
search and a checked model-relative bound; keep exhaustive search only as the
small oracle. Audit separability before adding heuristic complexity. Then connect
only the acquisition/adaptive and real-data paths needed for actual comparisons.
Retain the one-week deadline, tiny development, and all final research obligations.

## Workspace and scope

**2026-09-11 latest user deadline: new real experimental results within one week,
by2026-09-18; internal report target12:00 Asia/Shanghai.** Prioritize actual
model+real-data+Neo4j/Fuseki experiment and retained comparison denominators.
Do not substitute toy/replay or old FinBench results. Finish current interface
work, then move directly to the experiment path; defer UI/nonessential extension
and large catalog rebuilds. Full system objective is unchanged.

- Authoritative working repository: `/Users/anthonyche/Developer/XGAP`.
- Branch at entry: `codex/m13e4-grailqa-semantic-paper-protocol`; base `a91aed6`.
- The ChatGPT mirror repository is stale; synced `sources/` remain read-only.
- Goal: complete the agentic federated system through measured milestones,
  preserving prior scientific choices and accepted/raw experiment artifacts.
- Current collaboration: one bounded read-only proof/API review; no delegated edits or external runs.

## User schedule and stopping condition

**Recovery verified:2026-09-11 10:15 +08:00**, clean d9c2858 and current time
checked. The interruptible overnight pause completed; xgap heartbeat restored
to hourly through the app tool. No current pause remains. The previous turn
honored the user-scheduled pause; it was not an engineering blocker.

Historical September10 evening instruction:

**New instruction, 2026-09-10 evening:** complete the current capability
milestone, then stop development until **2026-09-11 10:00 +08:00**. Do not start
the next milestone tonight. The existing xgap heartbeat was updated through
the app tool to next run at10:00 local time (daily10:00 cadence); upon that
scheduled recovery restore its previous hourly cadence and continue toy-first.
Before the recovery time, do not run work or poll terminal handles to fill the
pause. The overall Goal remains unfinished; do not mark it complete/blocked.

Historical schedule:

The user-requested overnight pause ended at **2026-09-10 10:00 +08:00**.
Work resumed at 10:03 and the existing `xgap` heartbeat was restored to ACTIVE
hourly cadence. D198 had completed at commit `65ad96c` before the pause.
Do not treat the old overnight stopping instruction as a current pause.
Local scheduled execution needs this Mac and the Codex app available.

The agent cannot directly push to ChatGPT mobile or verify phone delivery.
Do not claim a phone push occurred. The system objective remains unfinished.
The goal-status tool reports ACTIVE on September 10 at 07:32 UTC; the existing
hourly heartbeat remains ACTIVE. The earlier blocked observation is superseded.
Do not mark the broad system goal complete or blocked to imitate a pause.
The scheduled morning recovery has occurred; normal authorized work continues.

## Accepted milestone — T3-B execution memory

User explicitly clarified that XGAP is a research prototype: prioritize paper
experiments, correctness/reproducibility/fair costs over perfect implementation.
General streaming/product UI/arbitrary partition discovery are not automatic
experiment prerequisites. This user direction is persisted in docs/goal.md.

Base8db41fa; scope decisions/semantic_execution_memory_v1.md. Existing MemoryStore
now joins the common question entry through exact-context observation reuse,
explicit environment episode and finite age. Historical acquisition calls/time
stay separate from fresh work. No answer caching, compiler/gold change or new
general framework. First local test command exited4 before running because of
a nonexistent filename; corrected96791 passed112/5.53s; final10840 passed148/7.50s.
Native8381 exit0:5 cold+5 warm programs,18 candidate answers,10 independent targets
and old slice pass. Native37/37 source hashes match; owned services94034/93927
stopped normally. Cold18 observations+9 executes; warm0+9, total73 test-query calls
including validation/references/slice. No latency claim.

Full90283 exited0:3481 passed/38 skipped in691.20s,24 entrypoints. All handles
are terminal; no source/test edits after launch,39/39 recorded hashes match.
Do not restart this gate. Log: /tmp/xgap-t3b-memory-acceptance.log. Receipts/report:
experiments/artifacts/semantic_execution_memory_20260911.json and
report/semantic_execution_memory_20260911.md. Remote3804011 has no new observation;
its last actual state wasPENDING/Priority, estimated18:28:27 Beijing. No external
action or failed-access retry this turn. Prototype and one-week result goal remain
active; finish current gate then the real model/data experimental path.

## Accepted predecessor — T3-A static selection

User requested an implementation-versus-verification audit while the GPU queues.
See report/engineering_completeness_20260911.md: deterministic bounded backbone
exists and is live-tested; LLM adapter exists but real-model evidence is pending;
memory/adaptive/UI exist in older paths with generic-entry integration gaps;
general streaming/query cancellation and broader partition/physical search are
actual missing capabilities. Do not equate absent paper tests with absent code,
or call the whole original Goal complete after a five-question gate. Current
catalog entries inspected read existing artifacts; old-format migration is not
evidence of per-question catalog rebuilding.

Base 73575c7; scope frozen in decisions/static_semantic_selection_v1.md. Add an
optional fixed backend order through the ordinary question/bind/compile/execute
entry. No observations or fabricated snapshot, no semantic/compiler/gold changes.
The existing costed selector stays default. Focused76409 exit0:115/4.70s.
Native64202 exit0:5/5 programs,18/18 candidate answers,10/10 independent targets
and old two-engine slice pass. All recorded source hashes match; owned services
stopped normally. Selected question executions use0 observation+9 execution calls;
candidate/reference/slice validation calls remain separately accounted. Tiny
timings do not establish a speedup. Report: report/static_semantic_selection_20260911.md.

Full75266 exited0:3457 passed/38 skipped in680.07s; all24 harness/example
entrypoints passed. Log /tmp/xgap-t3a-static-acceptance.log. All handles are
terminal; no source/test edits after launch, all38 receipt hashes match and
original frozen fixtures are unchanged. Receipt/docs are accepted. Do not
repeat passing gates without a new change. Push94922 remains failed128 and
is not retried. Whole Goal remains active; no current pause.

Actual remote progress supersedes the historical observations below. User staged
bc2bb67 from the fixed offline package and reported exact-token preflight success,
zero external calls (raw preflight checks not yet retrieved). Actual H1003803984
stayed PENDING/Priority with no GPU; one pending-only cancellation was confirmed
by scontrol CANCELLED,RunTime00:00:00,AllocTRES(null) and empty squeue. The user
then submitted **L40S3804011** using the explicit pipeline2 contract, one hour,
no requeue and excluding069. Independent receipt directory:
/home/hxc859/xgap-toy-model-bc2bb67/l40s-switch-from-3803984.
Do not rerun submit.sh or remove submission markers. Actual3804011 squeue now
shows PENDING/Priority, no assigned node, estimated06:28:27 UTC-4=18:28:27 Beijing.
Actual model responses are still unavailable. Previous L40S test-only3804005
estimated gput064 at07:42:27 UTC-4=19:42:27 Beijing; this is not a reservation.
User date03:46:19-04:00 confirms server offset. Model recordings return to local
native --agentic-semantic --interpretation-recordings before any large dataset.
No new browser action or retry occurred; user executed all remote mutations.
Receipt: experiments/artifacts/cwru_toy_model_submission_20260911.json.

## Accepted predecessor — T2-C model adapter software; live gate pending

T2-B committed locally asbea9321afb29c951ff11f7fa7a2de01fa59eaedd.
Push94922 is terminal128: connection closed by127.0.0.1:1082. Upstream remains
174393d; no retry. All earlier handles are terminal. Never treat the failed
push as a remote source update. New offline bundle will carry exact local source.

T2-C scope frozen in decisions/live_toy_interpretation_v1.md. New provider and
prompt/schema use existing transport/token guard, one call/no repair, observable
unknown token usage and failure provenance. Model-only runner has five fixed
questions with input context identical to the native entry; native harness can
replay their recordings. Existing graph/gold/catalog and compiler/runtime unchanged.
New job runs tiny connectivity only, one hour, owned model cleanup; H100 explicit
health profile and existing L40S fallback. At this software gate there was no job
submission or actual model call; later submission observations are above.

Focused35421 exit0:157/7.17s. Focused22612 exit0:114/11.40s. Native65485 exit0:
5 programs,18 candidate answers,10 independent targets and old slice; source35/35
match, services78895/78853 stopped normally. These are controlled template records,
not Qwen replies. Output /Users/anthonyche/xgap-data/t2c-native-recorded-interpretation-20260911,
log /tmp/xgap-t2c-native.log. No native rerun needed absent a new change.

Final full32472 exit0:3421 passed/38 skipped in676.02s; all24 harness/example
entrypoints passed. All handles terminal. No source/test edits after full launch. Receipt
experiments/artifacts/toy_model_interface_20260911.json and report
report/toy_model_interface_20260911.md accepted for software, real model pending.
Producer commitbc2bb67774910225a2e3842da26cb87fa676bf54 is local and accepted.
Verified offline package /Users/anthonyche/Developer/XGAP-deliverables/xgap-toy-model-bc2bb67.zip
is3927051bytes, SHA256ad38ad1118834ca1536ccb7b74f0cb44315b90c038cd33b7bef3d68ceee935e3.
Bundle clone/checkout, source bytes, shell syntax and ZIP integrity checks passed;
see experiments/artifacts/toy_model_delivery_20260911.json. Independent Chrome
createBrowserTab for the portal also timed out after30s; no upload/submission
confirmed through the browser. Do not repeat failed browser actions. The manual
upload/stage/submission has since occurred, as recorded in the current section.
All local handles are terminal. No source/test change after final acceptance.
Later documentation-only commits do not change the fixed producer package.
Do not automatically retry failed Git push or old browser access. Model-only
remote responses return to the same native tiny graph before any large-data work.

## Accepted predecessor — T2-B Interpretation entry and provider replay

Previous turn was progress:174393d committed/pushed T2-A, clean HEAD=upstream.
T2-B scope was frozen in decisions/interpretation_entry_replay_v1.md. New common
provider-neutral question entry validates typed programs and explicit hard
constraints before the pinned catalog/execution chain. Existing deterministic
intake now carries optional executable predicates; the adapter moves legacy
hole ownership out of executable parameters. Two tiny input templates retain
all old gold. Provider response/failure journals support zero-external replay;
general backend replay is deferred, not claimed complete.

First focused43107 terminal1:67 pass/5 failures from ownership parameters;
fixed by the adapter. Focused36774 terminal0:72/2.37s; expanded3432 terminal0:
74/2.39s; final84886 terminal0:75/2.39s. Native71146 terminal0:5/5 programs,
18/18 candidates,10/10 independent targets and old slice pass; all34 native
source hashes match and both services stopped normally. Daily81728 terminal0:
546/30.01s+18 demos; the later strict JSON identity case is in final focused/full.
Logs
/tmp/xgap-t2-interpretation-native.log and /tmp/xgap-t2-interpretation-daily.log.
Native output /Users/anthonyche/xgap-data/t2-interpretation-native-20260911.
Full85404 was deliberately stopped for an observed provider entity-authority gap;
terminal exit2:2504 passed/37 skipped/575.35s. New Interpretation rejects preset
entity candidates and passes a defensive request copy. Final focused49491 exit0:
77 passed/2.32s. Final full58858 is terminal exit0:3394 passed/38 skipped
in674.23s, all24 harness/example entrypoints passed. All test/native handles
are terminal. Log /tmp/xgap-t2-interpretation-acceptance-final.log. Native programs5/5 still match
current Interpretation exactly; the sole native source delta is the two admission
checks, verified by reconstructing the old bytes/hash. Other33 native hashes match.
Do not repeat these passed gates without a new change or concern. No source/test
changes after final full launch. All37 final source hashes match the receipt;
original tracked fixtures are unchanged. Receipt experiments/artifacts/toy_backbone_t2_interpretation_20260911.json
and report docs/report/toy_backbone_t2_interpretation.md are accepted.
Local commitbea9321 is retained; push failed as described above. T2-C now continues
the real model adapter and tiny connectivity package.

Current remote observation: CUA inventory found Chrome Pioneer terminal366873551
at hpc8, but getTab timed out before reading content or sending any server action.
This is not proof of expired login. The user returned two empty squeue outputs: no active/queued jobs. Their subsequent
sinfo shows gput072 H100 mixed/planned, gput073 allocated; L40S063/065/068 mixed,
069/070/071 mixed/planned,067 drained. CPU/GRES capacity is not idle GPU proof.
User returned both sbatch --test-only estimates,8CPU/64GiB/4h:
H1001: test identifier3803924,2026-09-11T06:26:34,gput072; L40S2 excluding069:
test identifier3803925,2026-09-11T04:13:07,gput064. These are scheduler-local
estimates (timezone unverified), not submitted/reserved jobs or GPU health proof.
The L40S estimate is2h13m27s earlier. No new job submission occurred.
Latest user gate: BEFORE quick-development acceptance, remote runs are ONLY
small-data model-health/full-chain connection tests; NO large dataset run.
Next remote package must test the tiny chain, not launch the old GrailQA18 run. The deadline and mandatory tiny
development are persisted in docs/goal.md, experiment_delivery_20260918.md and the existing
hourly heartbeat. Next use existing frozen real experiment protocols, not another
general-purpose framework milestone. Overall Goal remains active.

## Accepted predecessor — T2-A frozen resolution bundle

Base ffb7b47. Scope and gates were frozen in
docs/decisions/frozen_resolution_bundle_v1.md before implementation. The offline
publisher, pinned read-only reader and run_frozen_semantic_query now join the
existing catalog, executable typed bindings and optional ontology into one
version. Original gold and algebra are unchanged. The independently defined
finite language contract is docs/bounded_query_profile_v1.md; do not expand T1
into all possible query semantics. General replay and legacy GrailQA migration
remain separate work. No new model call or large dataset build ran.

Focused99761 is terminal exit0:87 passed/2.79s; daily61671 terminal exit0:
517 passed/27.82s plus18 original demo cases. Native23609 is terminal exit0:
5 agent programs/18 candidate answers/10 independent targets and old slice
correct; both owned services stopped normally, all31 native source hashes match.
Native output: /Users/anthonyche/xgap-data/t2-frozen-resolution-native-20260911.
Full acceptance2851 is terminal exit0:3362 passed/38 skipped in673.89s,
all24 harness/example entrypoints passed. All handles are terminal; never repeat
passed gates without a new change or concern. Log:
/tmp/xgap-t2-frozen-resolution-acceptance.log. No source/test edits after launch.
All36 final source hashes and5 frozen fixture hashes match; original tracked
fixtures are unchanged. Report docs/report/toy_backbone_t2_frozen_resolution.md
and receipt experiments/artifacts/toy_backbone_t2_frozen_resolution_20260911.json
are accepted. Commit/push and update the existing xgap heartbeat for this state.
Next: common Interpretation contract and minimal recorded-provider/tool failure
replay, followed by legacy catalog dependency migration on tiny fixtures.
No model or large dataset is a development prerequisite. Overall Goal active.

## Accepted predecessor — typed binding values

Base400f0cf; scoped decision docs/decisions/typed_binding_values_v1.md. Current
implementation and final native gate are ACCEPTED. Final broad24384 exit0:
3334 passed/38 skipped/670.66s and all24 harness/example entrypoints passed;
log /tmp/xgap-t1-typed-binding-acceptance.log. All handles are terminal; do not
repeat passed gates without a change. No source/test changes after broad launch.
Focused2033 exit0:208/5.48s; daily7865 exit0:489/26.35s+18 demo; final changed
reference replay60153 exit0:53/1.19s. Local native Jena ARQ references15/15 pass.

Retained native15 programs/32 candidate answers/27 independent targets and old
slice pass: V01–V04 from t1-typed-binding-native-final-20260911; V05–V15 from
t1-typed-binding-native-completion-20260911. Final selected plans15/15 identical
to recorded native execution; all candidate IDs match current enumeration.
Native sessions40877/50945/58476 terminated exit1 on reference-query mismatches,
not runtime answer failure. Completion73125 exit0; all owned service pairs
stopped normally. No native handles remain active. Current source differs from
first two native snapshots only in runner query-subset selection; later native
source hashes match exactly. Do not rerun accepted native cases without a change.

Receipt experiments/artifacts/toy_backbone_t1_typed_bindings_20260911.json is
accepted; report docs/report/toy_backbone_t1_typed_bindings.md records all
failures/costs. User asks for realized goals and the
distance to the full system after submission; report xgap_progress_20260911.md
is current. Overall Goal stays ACTIVE; the old overnight pause was completed.

Latest user clarification: XGAP need not implement every possible query. First
freeze a finite independently defined support profile, distinguish Interpretation
from representability/compiler/runtime correctness, close included gaps and move
to T2. See docs/decisions/bounded_system_scope_v1.md. Outside-profile forms do
not become an endless implementation backlog. Existing query guards are not
performance evidence; proposed3-hop workload settings are not a new enforced
universal limit. Benchmark choices and full coverage denominators stay fixed.

## Accepted predecessor — native Boolean conditions

On base bafce8e, total AND/OR/NOT is ACCEPTED for modern paths and Match.
Decision: docs/decisions/native_boolean_conditions_v1.md. Separate overlay has20
complete path gold chains and4 typed Match programs; old graph/gold stay frozen.
Report: docs/report/toy_backbone_t1_boolean_conditions.md. Overall Goal ACTIVE.

Focused94086 terminal exit0:296 passed/15.96s. Native18573 terminal exit0:
40/40 path +40/40 refs,8/8 Match +8/8 refs,3/3 plans/6/6 candidates and old slice.
Both services stopped normally. Daily27207 terminal exit1:398 pass/1 failure
(Match lost explicit Nodes capability rejection). Nodes/Selection admission
restored, replay16709 terminal exit0:71 pass/2.88s. Earlier collection error was
a wrong import, fixed; local fixture/rejection failures remain in the report.

Follow-up71425 terminal exit0:8/8 Match +8/8 refs,3/3 plans/6/6 candidates,
old slice pass, normal shutdown. Daily67642 terminal exit0:401 pass/25.98s+18 demo.
Broad65353 terminal exit2:2 collection errors due to a downstream import of
_OPERATORS removed during cleanup. Restore the symbol, explicitly preserve the
old Freebase split adapter's conjunctive scope so it cannot drop new Boolean
shapes; local dependent replay5669 terminal exit0:140 pass/3.88s. No GrailQA
build/run. Current compiled40 path +8 Match plans match successful native
records exactly (48/48 offline comparisons). Native follow-up's only final
source hash difference is directed.py dependency-symbol restoration, not queries.

Final broad69433 terminal exit0:3246 passed/38 skipped/670.40s, all24
harness/example entrypoints pass. Log /tmp/xgap-t1-boolean-acceptance-final.log.
Every Boolean test/native handle is terminal; do not poll/repeat passed gates.
No source/test edits after final broad launch. All final recorded source and
fixture hashes rechecked. Receipt experiments/artifacts/toy_backbone_t1_boolean_conditions_20260911.json.
Broad was restarted only after its terminal collection failure was fixed.
This Boolean step is accepted; full T1/T2/T3 and overall Goal remain active. Previous goal turn
committed the requested report; this turn implements and obtains native evidence.

Next typed-binding work has a concrete offline probe (no production edits, no
external calls): /tmp/xgap-next-typed-binding-observations.json. Current SUM
accepts numeric strings, converts integer9007199254740993 to9007199254740992.0,
and rejects a typed RDF decimal; MIN mixes bool/numeric; grouping splits1/1.0;
sorting None with numeric fails. These observations identify remaining type
contract/implementation work, not a new accepted milestone. Define the intended
binding-level scalar/nullable/group/aggregate/order contract before fixing;
keep audited PathSet Selection semantics unchanged.

## Accepted scoped predecessor

T1 finite nested path scopes is ACCEPTED on base861e043. The previous
goal turn was progress: finite repetition was implemented, measured, committed
and pushed. Current scope is in docs/decisions/scoped_path_execution_v1.md.
A new explicit coordinator placement composes supported native subexpressions,
retaining local path modes/SHORTEST before enclosing filters. Final full-path
intersection applies the independently compiled WALK candidate conditions, then
original selector. Existing fast native plans stay available; no graph/gold
oracle is loaded in runtime. Shared subexpressions execute once. The cost model
has an explicit uncalibrated Cartesian/power proxy for the new path work.

New15 complete gold chains pass logical/reference/independent RDF and production
semantic-DAG execution. Focused37631 exited0:155 passed/11.32s. Initial3655
terminated with115 pass/one obsolete nested-WALK rejection expectation; migrated
to the still-unsupported one-query non-WALK boundary. Initial1204 terminated with
16 pass/four test-assertion mistakes (tool-result envelope and branch limit);
corrected, then the focused gate passed. A local exploratory RDFLib probe used
a non-thread-safe parser concurrently and failed; the new test client serializes
that parser only, as existing planning tests do. No live external retry occurred.

Native31786 is terminal exit1 after30/30 semantic/native executions and30/30
independent targets passed (86 compiled calls +30 reference calls). The subsequent
planning helper failed locally on missing optional ordered metadata, after its
N01 run but before checkpointing that run. Both services stopped normally. That
uncheckpointed planning work is not assigned a fabricated measured cost. The
comparison now defaults to unordered, consistent with semantic execution; two
local replay tests cover a match and a mismatch. First replay89075 exit0:22 pass.
Daily79242 exit0:355 pass/22.16s. Follow-up native64470 exit0:3/3 planning programs,
6/6 candidate answers and old slice pass;14 observations+7 serving+7 extra candidate
validation+2 slice calls. This follow-up did not repeat the60 passed targets.
Daily58497 exit0:357 pass/22.55s. Both native service pairs stopped normally.

Review identified a separate admission issue: replacing the original mode with
WALK for the superset could conceal invalid input. Original semantic validation
now runs first; focused51426 exit0:23 passed/7.56s including invalid mode/selector
replay. Broad62508 was intentionally interrupted for this code change, terminal
exit2:1263 passed/3 skipped/139.12s, not an acceptance pass or a lost handle.

FINAL gates: native59889 is terminal exit0, planning3/3, candidates6/6 and old
slice correct, all29 source hashes match; daily59218 is terminal exit0,358
passed/24.12s plus18 demo. Broad71124 is terminal exit0:3203 passed/38 skipped
in663.04s, all24 harness/example entrypoints passed. Every test/native handle
from this milestone is now terminal; do not poll or repeat these gates. Logs:
/tmp/xgap-t1-scoped-planning-final.log, /tmp/xgap-t1-scoped-daily-final.log,
/tmp/xgap-t1-scoped-acceptance-final.log. Native output:
/Users/anthonyche/xgap-data/t1-scoped-planning-final-20260911. The30+30 target
records remain in t1-scoped-native-20260911; admission-only changes are tested
separately, never presented as a full target rerun. This scoped step is accepted.
Report: docs/report/toy_backbone_t1_scoped_paths.md; durable receipt:
experiments/artifacts/toy_backbone_t1_scoped_paths_20260911.json. Next: remaining
native condition/typed aggregate-order semantics, then T2 catalog lifecycle and
minimal replay, then real-model/mini integration and final evaluation. T1 as a
whole, T2/T3 and the full system Goal remain unfinished.

## Accepted finite repetition predecessor

T1 Optional/finite Bounded repetition is ACCEPTED on top ofd9c2858 after
the September11 morning recovery. See `docs/decisions/finite_regex_repetition_v1.md`.
Optional=Nodes union child. Finite Bounded unions exact child powers, applies
the existing Recursive(mode,max_depth=1) to positive powers, and adds Nodes
outside when minimum=0. No existing algebra definition changed. Native root
finite ranges and compositional Optional reuse branch budgets/selectors;
nested non-WALK scopes and unbounded minimum>=2 without a finite query depth
remain explicit gaps. A nullable child inside positive SHORTEST repetition
participates in minimum length; a separate zero-repetition Nodes branch does not.
The selector now records that difference. Parser accepts exactly zero upper
bound, capability assessment reflects real finite lowering, and old original
gold files remain frozen. New13 full independent chains have local exact plans,
answers, independent RDF and semantic-DAG entry checks.

Terminal gates: compatibility92966 exit0,172 passed/2.14s; initialnew8908 exit0,
22 passed/1.52s; focused2471 exit0,226 passed/4.30s; interface34702 exit0,
42 passed/1.89s. No failed test/query observed in these runs. New native/daily/
broad handles:7181(daily) is terminal exit0,335 passed/15.12s plus18 demo;
50965(native) is terminal exit0,26/26 compiled and26/26 independent answers
plus the old slice correct. Both services stopped normally, no kill/retry;
15 source and42 old/28 new fixture hashes match. Broad81593 is terminal exit0:
3180 passed/38 skipped/645.66s, all24 harness/example entrypoints passed.
All current test/native handles are terminal; do not poll or repeat passed gates.
Receipt: experiments/artifacts/toy_backbone_t1_repetition_20260911.json; report:
docs/report/toy_backbone_t1_repetition.md. Next: same-toy remaining nested path
scopes/typed semantics, then T2 catalog lifecycle and minimal replay, then T3.
This finite repetition step is accepted; full T1/T2/T3 remain unfinished.
Logs `/tmp/xgap-t1-repetition-{fast,native,acceptance}.log`;
native output `/Users/anthonyche/xgap-data/t1-repetition-native-20260911`.
Do not relaunch existing work because an observation times out. The overall
system Goal remains active, and the overnight pause has ended.

## Accepted capability predecessor

T1 semantic capability admission is ACCEPTED on top of2f978b8. The prior
goal turn made progress: orientation code and the consolidated report were
committed/pushed; this turn changes the executable admission boundary.
Pure compilation now resolves requested native/read/coordinator capabilities
to runtime nodes owned by that semantic operator. Existing native profile and
shape checks still apply. Unknown or misplaced requirements cannot borrow a
child's capability or silently disappear. Eight explicit overlays reuse the
original complete semantic chains:16 of28 placements admitted,12 rejected.
Focused gate120 passed/3.51s, original session8138 exit0.

Daily47096 is terminal exit0:300 passed/13.51s plus18 demo answers. Native34608
is terminal exit0:8/8 queries,16/16 admitted placement answers and old slice
correct;12 disallowed placements retained as rejected.20 observations+14 serving
calls;15 alternative-validation calls and2 old-slice calls separate. Both owned
services stopped normally, no kill/retry, source hashes match.
Broad91696 is terminal exit0:3145 passed/38 skipped/667.51s, all24 harness/example
entrypoints passed. All current test/native handles are terminal. No production
source changed after broad launch. Do not repeat accepted checks without new evidence.
Logs `/tmp/xgap-t1-capabilities-{fast,native,acceptance}.log`.
Native output `/Users/anthonyche/xgap-data/t1-capabilities-native-20260910`.
Decision `docs/decisions/semantic_capabilities_v1.md`; native and broad acceptance
passed. Report `docs/report/toy_backbone_t1_capabilities.md`. Stop after commit/push
per the new user pause; resume at2026-09-11 10:00 +08:00. This is not a blocker.
The graph and original gold remain unchanged. Overall Goal stays active.

## Accepted orientation predecessor

T1 orientation/reference closure is ACCEPTED on top of07e0c7a.
Separate semantic decision: `docs/decisions/path_orientation_v1.md`.
Add explicit XGAP Reverse(PathSet), preserving Edges(G) and stored identities;
IN lowers through Reverse, UNDIRECTED through Union of both orientations.
The bounded native compiler expands undirected branches inside existing budgets.
M9 explicitly rejects Reverse instead of silently treating it as OUT.

The original graph and all original gold files stay frozen. A new orientation
fixture contains9 complete chains and18 independent targets; a separately
versioned T15 logical expectation replaces the old semantic placeholder only
when the development harness explicitly opts in. Original18 logical/reference
checks now pass in that current harness. New tests include Reverse laws for all
five recursive modes, identity/loop/parallel-edge witnesses and rejection of
non-PathSet inputs. Initial focused collection failed because a test imported
GroupKey from a namespace that does not export it; corrected tests passed212
in9.35s (session11123 exit0). Final fast gate180 pass/12.10s (58672 exit0), with
all18 demo answers and logical expectations correct. No actual query failure
was observed in these local checks.

Native session67522 completed exit0:18/18 production-compiled executions and
18/18 independent native targets pass, plus the original two-engine slice. Both
owned services stopped normally without kill escalation or retry. Raw root
`/Users/anthonyche/xgap-data/t1-orientation-native-20260910`, log
`/tmp/xgap-t1-orientation-native.log`. Recorded source/fixture hashes match. The
explicit-overlay offline CLI also passed18/18 logical plans, reference answers
and independent SPARQL targets (session63085 exit0); output
`/tmp/xgap-t1-orientation-logical.json`. First broad session61777 has exited1:
3 failed/3114 passed/38 skipped in670.13s. It exposed the separate candidate
assessment scanner still declaring IN/UNDIRECTED logically unavailable. The
scanner now uses profile m5_path_algebra_orientation_v1 and reports actual
logical support; backend_execution_verified remains false. Updated old tests
retain genuine M9 unavailability instead of equating it with logical support.
Capability consumers now pass261/skip20 in3.18s (session14689 exit0). Related
local stale-assertion failures are preserved in capability replay logs. Native
query source remains unchanged and its successful gate is not repeated. A final
broad acceptance has COMPLETED in original session96124, exit0: **3,117 pass /
38 skip in662.26s**, all24 harness/example entrypoints pass. Log
`/tmp/xgap-t1-orientation-acceptance-final.log`. Daily harness wiring then added
the candidate-assessment module; fast session97917 exited0 with272 pass/12.56s
and all18 logical/reference demo answers correct. No production source changed
after final broad launch. All native/test handles in this step are terminal;
do not poll or repeat accepted checks without new evidence.
Original18 path programs and older binding/planning steps remain accepted.
This orientation step is accepted. Broader semantic capability admission
(required_capabilities), remaining path/typed semantics and T2 catalog/runtime
freeze/replay remain next. Overall T1/T2/T3 and the system Goal remain unfinished.
See `docs/report/toy_backbone_t1_orientation.md` and the durable receipt.

## Accepted binding/control predecessor

T1 semantic binding/control native gate PASSED: **5/5** controlled programs,
**18/18** placement candidate answers, **10/10** independent Cypher/SPARQL
references and the original T18 two-engine slice. Corrected native session90516
exit0; owned services stopped normally. Raw root:
`/Users/anthonyche/xgap-data/t1-binding-native-20260910-corrected`.
The first native session37831 exit1 after B01's four correct candidates: the
independent-reference adapter omitted typed RDF result encoding. Preserve that
failure root without retry. Corrected code first passed local RDF replay.

The new typed binder applies ENTITY/PREDICATE/TYPE/SOURCE/CONSTRAINT slots to
actual program meaning; entity ambiguity and unsupported/unused constraints
prevent backend dispatch. Existing GoalLoop resolution, candidate planning,
cost selection and execution now connect. No LLM or catalog build is required.
Named typed predicates are conjoined with existing Match/Traverse/Filter
conditions; opaque constraints and unsupported owners remain explicit gaps.
Physical costs cannot choose ambiguous meanings. Original gold is unchanged.

New module29 pass/1.06s (session84604), compatibility57 pass/24.02s (48121),
earlier toy fast gate154 pass/11.18s (81878). Broad acceptance COMPLETED in original
session11079, exit0: **3,098 pass / 38 skip in665.34s**, all24 harness/example
entrypoints pass. Log `/tmp/xgap-t1-binding-acceptance.log`. Production source and
frozen fixture hashes match native measurement. All native/test sessions are
terminal; do not poll or rerun accepted checks without a new concern. This
binding/control connection is accepted; the whole system Goal remains active.
27 observation/serving calls,25 validation-only alternative calls,10 independent
reference calls and2 old-slice calls are separate. No live LLM/paper result.
See [the binding report](report/toy_backbone_t1_semantic_binding.md).

Next close M5 IN logical/reference and remaining path/typed semantics, then T2
Interpretation plus catalog freeze/runtime-only lookup and minimal failure
replay. This connection does not imply full system acceptance or replace the
large-data EQ1–EQ5 obligations. Do not wait for GPU or build GrailQA to develop.

## Accepted candidate-planning predecessor

T1 candidate planning native gate PASSED: original session55823 exit0, **8/8**
programs selected and executed correctly; **28/28** complete placement candidates
match frozen gold. Original two-engine slice passes. Raw root:
`/Users/anthonyche/xgap-data/t1-planning-native-20260910`. Owned services stopped
normally, no retry. Planning/serving used28 observations+14 executions=42 calls;
validation-only alternatives added38 calls; the old slice adds2. These are tiny
correctness measurements, not a calibrated optimizer/performance claim.

Focused final session21349 exit0: **106 passed in2.68s**, log
`/tmp/xgap-t1-planning-focused-final.log`. First two local runs exposed invalid
test replica mapping IDs, uncaught compiler-capability exceptions and RDFLib
parser concurrency. The latter exposed a production scheduler exception-accounting
gap now repaired and independently tested. No remote failure/retry occurred.
Initial/focused/focused2 logs remain. A misnamed focused3 test command ran no tests.

Broad shared-runtime acceptance COMPLETED in original session **6473**, exit0:
**3,069 passed / 38 skipped in657.30s**, all24 harness/example entrypoints pass.
Log `/tmp/xgap-t1-planning-acceptance.log`. Production source is unchanged after
launch; source and frozen fixture hashes match the native run. All current
acceptance/native processes are terminal. Do not poll or repeat accepted checks
without a new source change or concern. This candidate-planning step is accepted. See
`docs/report/toy_backbone_t1_candidate_planning.md` and its durable receipt.

The new source declaration requires complete equivalent replicas of one logical
snapshot; availability does not establish equivalence. Source roles remain
explicit, internal Traverse splitting is not implemented. A missing snapshot
profiles every unique fragment once; a compatible snapshot may be supplied.
Native observations and all serving calls are charged. Linear coordinator
estimates remain proxies. Current mainline still needs IN logical/reference
closure and integration with semantic admission/control, followed by T2/T3.
Do not build catalogs, wait for GPUs or launch large data to test these gaps.

## Accepted semantic DAG predecessor

T1 semantic DAG native gate PASSED. Native session92465 exited0: **36/36**
original path queries through typed semantic programs, **8/8** new compositions,
**8/8** independent Cypher references and the original federated slice. Six new
cases actually use both engines, two intentionally test one-source behavior.
Both owned services stopped normally without retry. Raw root:
`/Users/anthonyche/xgap-data/t1-semantic-native-20260910`.
Focused log `/tmp/xgap-t1-semantic-focused.log`: **137 pass in9.80s**, process
already terminal; original focused session ID was not retained in the continuation.
Initial session78925 passed35 tests. No focused/native failure in this step.

Shared-runtime broad acceptance COMPLETED in original session **42090**, exit0:
**3,049 passed / 38 skipped in657.66s**, plus all24 harness/example entrypoints.
Log `/tmp/xgap-t1-semantic-acceptance.log`. All current native/test processes are
terminal; do not poll or repeat them without a new source change or concern.
No production source changed after launch. The semantic composition step is accepted. The compiler now composes all nine
semantic operator kinds in an explicit profile with declared source placement;
this is not automatic optimal planning or arbitrary-program support. See
`docs/report/toy_backbone_t1_semantic_dag.md`. Next connect candidate generation,
existing cost selection and admission/control, and reconcile IN reference
lowering, preserving the tiny slice. T1/T2/T3 and the overall Goal remain open.

## Accepted bounded-path predecessor

T1 bounded-path native gate PASSED: all **18 frozen queries on both real
engines (36/36)** produce the exact complete gold paths through production
native expansion and the coordinator selector. The original two-engine T18
slice remains correct. Native session 91427 exited 0; both services stopped
normally, no retry. Raw root `/Users/anthonyche/xgap-data/t1-bounded-native-20260910`.
Focused final session 25002: **266 passed / 1 skipped in 10.97s**. Initial local
failures (boolean FILTER in an RDFLib union, and old validation ordering) are
preserved; gold fixtures are unchanged. Measured source and fixture hashes match.

Broad acceptance COMPLETED in original session **11810**, exit 0: **3,006
passed / 38 skipped in 669.07s**, log `/tmp/xgap-t1-bounded-acceptance.log`.
The harness and 20 script examples passed; the three newer examples passed
separately in session32275 exit0. All24 harness/example entrypoints passed.
The acceptance shell now includes those three for future runs; only this wiring
and documents/receipts changed after the measured production code. Do not
repeat these accepted checks without a new source change or concern.

Native expansion supports Rel/Seq/Alt and a root finite Plus/Star, with explicit
branch/edge budgets. Coordinator selectors reuse the existing SolutionSpace
functions; they are timed runtime work. The M5 IN lowerer gap, nested/unbounded
native recursion, general partitioning and Interpretation/catalog/replay remain
open; all 18 fixture executions do not prove the entire system complete.

That former next boundary is now covered by the semantic DAG compiler above
for its explicit profile. runtime/planning.py still selects among caller-supplied
candidates; automatic candidate generation and source choice remain next, alongside
orientation-aware logical/reference support. T1 is still in progress.

## Earlier T1 RDF identity step

T1 is IN PROGRESS. Its RDF edge-identity step is verified: an explicit reified
edge encoding preserves parallel-edge resource IDs and supports edge-property
filters through the production directed compiler/fragment adapter. Original
native session 60008 exited 0 with **16/16 compiled paths correct** (8 fixtures
on each real Neo4j/Fuseki backend); the two-backend T18 slice remains correct.
Both owned services stopped normally. Raw root:
`/Users/anthonyche/xgap-data/t1-rdf-native-20260910`.
Focused checks: **185 passed / 1 skipped in 9.82s** (session 62974); separate
Freebase/M9 compatibility: **99 passed in 2.63s** (49131). Harness and toy example
pass. Measured source/fixture hashes are unchanged; all gold files remain frozen.
No new broad regression was run for this partial T1 step. Daily targeted tests
plus the live tiny slice follow the user's latest development rules.
Next: node-only/Union and bounded recursion/selectors through production native
compilation, with an operator-by-layer coverage table. IN native rows are now
verified; the M5 IN lowerer gap remains distinct. Full T1/T2/T3 are unfinished.
See `docs/report/toy_backbone_t1_rdf_identity.md` and its durable receipt.

## Accepted T0 predecessor

T0 is COMPLETE for fixtures and first compiled true-backend slice. Original
broad regression session **63579** exited 0: **2,963 passed / 38 skipped in
657.90s**, log `/tmp/xgap-t0-full.log`. No executable source changed after the
full launch; do not rerun accepted checks without a new concern. Focused: **76 passed in
7.73s**, session 76238 exit 0. Harness and 23 examples: **24/24 pass**, session
81517 exit 0. Five nodes/eight edges/eighteen complete gold-chain fixtures are
in `datasets/backbone_toy_v1`. Reference logical/answer checks pass 17/18; IN
remains a recorded old-lowerer gap. Independent RDF targets pass 18/18.
Native session 80488 completed exit 0: 36/36 independently authored target
queries pass on real tiny Neo4j/Fuseki stores, and the production-compiled
two-engine T18 slice returns `a/e4/c` with two calls. Both services stopped
normally without escalation. Raw root: `/Users/anthonyche/xgap-data/t0-native-20260910`.

An actual compiled RDF probe reproduces parallel-edge loss: T03 expects three
paths but gets two bindings; T02 8→7, T05 6→4, T15 2→1, T16 5→3. The plain
predicate is bound as an edge ID. This motivated the explicit representation support now verified in T1;
the fixture and legacy plain-RDF behavior remain unchanged. Do not remove the parallel edge or use
expected answers to reconstruct lost paths. Broader IN/Union/recursive/selector
gaps remain. See `docs/report/toy_backbone_t0_v1.md`.

**Latest user direction: toy-first development.** Read `docs/goal.md` before
implementation. T0 (minimal graph + 18 core query fixtures + first complete
deterministic vertical slice) is accepted; T1 full operator coverage is next.
Separate Interpretation from deterministic
planning. Runtime must never build a GrailQA catalog; offline build/freeze and
runtime lookup are separate. Add failure replay. Module tests and toy E2E drive
development; GrailQA-mini follows for integration, large datasets for final
evaluation. The app Goal remains ACTIVE; its tool cannot edit objective text,
so the new instructions are persisted in the required Goal file and heartbeat.

D208 is **deferred before native measurement** by this user direction. Its
runner is implemented at `7e09a56`; final focused session 22986 exited 0 with
**112 passed / 1 skipped in 1.81s**. The later T0 broad suite also covers this
software, but its native campaign has not run and no D208 campaign completion
is claimed. Reuse the runner for toy tests if
useful; do not run the displaced campaign merely to close it. Former scope:

D208 proposed a fixed-semantics CPU comparison over the three existing
first-shard type/name queries. Reuse both native stores, compile the existing
Neo4j→Fuseki and full-Fuseki plans, and use the same scheduler/normalization
timing boundary. Freeze 2 warmup + 8 measurement rounds with paired alternating
AB/BA order and rotated query order (60 executions). Retain failures and stop
without retry. Verify actual answers against existing independent Arrow results
after timing. Allowed: experiment runner, tests and records; forbidden: changes
to semantics, catalog, data, LLM inputs or historical results. This is a local
development diagnostic, not GrailQA accuracy or a formal new benchmark. See
`docs/report/freebase_cpu_paired_comparison_v1.md` for the frozen scope.

The first focused run found a measurement bug: an exception before a backend
report escaped the runtime and left the attempt count unknown. A small observed
client now increments before dispatch, retaining actual attempt counts even on
that exception. Preserve `/tmp/xgap-d208-focused.log` (44 pass / 1 fail / 1 skip)
and the separate final focused log. No real backend failed in that test.
CUA inventory observation timed out and reset its kernel in this cycle; no
remote mutation was made, and no fresh scheduler state is inferred. CPU work
does not depend on that observation route.

## D207 accepted predecessor

D207 software acceptance is complete after D206's actual hardware failure.
Scope: per-device minimal CUDA allocation/kernel/synchronization before
model load, and immediate readiness failure when the owned server process has
exited. Allowed changes are GPU/startup/readiness adapters, their tests and
records. No frozen model/catalog/spec, semantic metric, query algebra or running
checkout changes. Acceptance: controlled second-device ECC aborts before daemon
launch; healthy/legacy launch behavior and exact model checks remain; dead server
fails without waiting the full readiness budget; focused/full/examples pass.

Actual D207 acceptance: focused **51 passed in 20.58s**; original full session
60312 exited 0 with **2,922 passed / 38 skipped in 673.86s**; harness and all
22 examples pass (23 entrypoints). No source edits followed the full-suite
launch; only reporting records were completed. Seven controlled submission-helper
fixtures pass but are not Slurm observations. No corrected package has been
built/uploaded and no D207 job has been submitted. Do not rerun passed tests
without a new source change or concern. Receipt:
`experiments/artifacts/d207_startup_health_acceptance_20260910.json`.

Latest user priority: explain system maturity, GrailQA failures, test design,
actual results, baselines and research story. The delivered source-inspected
assessment is `docs/report/xgap_system_experiment_assessment_20260910.md`.
This assessment's development priorities are superseded by `docs/goal.md`:
the toy backbone comes first; the large-shard campaign and 8+4+1 diagnosis no
longer head the queue. Preserve FinBench/GrailQA final evaluation and every
EQ1–EQ5 requirement;
do not reframe the research around only successful tests. Reuse existing entity
linking/index/data artifacts when verified; do not repeat unchanged 964-shard
scans or inject evaluation entities into inference/data deployment. Time windows
in the report are conditional estimates, not guaranteed effect/completion dates.

D206 software/resource transition succeeded but actual model startup FAILED.
**No active experiment is currently established.** Original 3799513 is CANCELLED;
replacement **3799649 is FAILED / 1:0**. It started on gput069 at 16:17:42 Beijing
and finalized at 16:34:57 with six retained artifacts. The worker's first root
error at 16:29:11 is CUDA uncorrectable ECC; initial GPU 1 reported three volatile
uncorrectable ECC events. GPU capacity/type checks did not establish health.
No question inference output was obtained. Both final Slurm states were read.
The run cleaned up normally with no remaining GPU processes. Do not run its
success-only audit or either old submit/switch helper again.

Exclude gput069 until recovery is established. A read-only explicit
`sbatch --test-only --exclude=gput069` for two L40S estimated gput070 at
17:30:23 Beijing; this is not a reservation or submission. A preceding
SBATCH_EXCLUDE environment attempt still selected gput069 and is not valid
exclusion evidence. Use the explicit command option. Test-only prospective IDs
3799704/3799707 are not real submitted jobs. H100 remains preferred when available.

D206 final targeted: 105 passed in 7.17s; first focused: 245 passed/one fixture
failure, retained. Broad regression session **51749** completed exit 0:
**2,908 passed / 38 skipped in 661.11s**, log `/tmp/xgap-d206-full.log`.
Examples/harness session **94699** completed exit 0, all 23 entrypoints passed.
Do not repeat successful validation without a new code change or concern.
Producer `ada34316f11778f41d4b69560bc4d47e27d77d4e` is pushed. The v2 archive
was uploaded and its server hash verified:
`45d4cb60127996ff277e8406018089baad5e8db9350cc98591945ccbab9dba69`.
Remote package: `/home/hxc859/xgap-inline18-l40s-ada3431`; exact producer checkout:
`/home/hxc859/XGAP-inline18-l40s-ada3431`. Input pins were verified before the
single transition. Log: `slurm-xgap-grailqa-l40s-3799649.out`; run root:
`runs/cwru-grailqa-guarded-3799649` within that checkout.

After CUA reset Chrome browser ID is 2 (same extension/profile). Independent
agent-owned hpc7 terminal tab 366873317 handles this job; file tab 366873233
works. Other terminal tabs have concurrent user input: do not type there.
Use short chunks and verify the complete command before Enter. Never touch
credential inputs. Current browser IDs may change; inspect inventory if stale.

Preserve D206 failed artifacts. A later distinct deployment requires explicit
node exclusion, exact-source transfer verification and fresh submission
evidence. It must not displace the independent CPU/result priorities above.
No automatic retry of the old failed external action.
The old helper performed no retry; Slurm reported its default Requeue=1 with
zero observed restarts. Do not conflate these settings.
Report: `docs/report/cwru_gpu_fallback_v1.md`; receipt:
`experiments/artifacts/d206_gpu_fallback_20260910.json`.

## D205 accepted predecessor

D205 is COMPLETE for software and controlled native acceptance. The new
`freebase_question` API and explicit module CLI connect question/catalog input,
the guarded provider, exact grounded candidate preparation and native answers.
Identity/interpretation ambiguity remains explicit; finite row/call/time budgets
are enforced at their documented boundaries. Serving can omit full-Fuseki
verification, while optional verification retains separate outcomes and costs.
JSON positional goal bindings are immutable and reject conflicting positions.
No old model, catalog, spec, remote runner or algebra changed.

Full regression: **2,849 passed / 38 skipped in 627.60s**, original session
99584 exited 0. Focused: 178 passed in 2.29s. Harness and 22 examples pass,
23/23 entrypoints. Do not repeat successful checks without a new concern.
Three successful controlled HTTP-provider/native cases return the same expected
release with 1/2/3 backend calls for resource serving, explicit verification,
and scalar serving. The first scalar diagnostic used an invalid fixture key
and failed before backend calls; a separate scalar-only corrected diagnostic
passed. Preserve both traces. All owned services stopped normally, no reload
or SIGKILL. This is not a live Qwen run, accuracy result or speedup evidence.
Report: `docs/report/freebase_question_execution_v1.md`; durable receipt:
`experiments/artifacts/d205_native_question_execution_20260910.json`.

Next: compare physical plans with the same fixed interpretation on CPU and
obtain real model-generated anchored answers on inference-owned facts when a
model is available. The historical D204 semantic-only run is terminal; its
question/model inputs remain frozen. Document inventory at this checkpoint was
74 full / 7 selected / 0 pending Markdown, plus three reviewed PDFs.

## D204 historical H100 observation and continuing GPU policy

The user completed the original authenticated checkout and submitted H100
job **3799513** once with exact runner `6b32b97`. It remained PENDING / Resources
and was subsequently cancelled while pending by the authorized D206 transition.
Its replacement **3799649 FAILED**, as recorded above. Original source, package and
submission evidence remain unchanged under `/home/hxc859/XGAP-inline18-6b32b97`
and `/home/hxc859/xgap-inline18-6b32b97`. Do not run its submission or audit
helper for the replacement. Its old offline ZIP is uploaded/hash-verified but
was never extracted or executed. Historical details are preserved in
`docs/report/grailqa_inline18_remote_execution_20260910.md`.

Catalog fa07c25b…308e8, original 18 question IDs and cached Qwen/tokenizer
revision 9216db5781bf21249d130ec9da846c4624c16137 remain fixed. D206 changes the
explicit deployment contract/spec identity, not inference settings. Backend
execution remains false and paper admission remains false for this run.
The user explicitly authorizes compatible GPU fallback when H100 is unavailable.
Preserve full BF16 model, actual hardware identity and one runnable experiment.
Do not silently quantize/shrink, claim hardware equivalence, or automatically
retry a failed external action. 3796988 showed no catalog-coverage gain; keep
v1 fixed and do not run another catalog scan to delay answer engineering.

## D203 accepted predecessor

D203 controlled software/native acceptance is complete. Broad regression ended
in original session 39813: **2,827 passed / 38 skipped in 643.80s**, exit 0
(`/tmp/xgap-d203-full.log`). Do not repeat passed tests or native queries without
a new change or unresolved concern. Report:
`docs/report/grounded_candidate_execution_v1.md`. The new opt-in preparation
interface reruns typed/canonical grounding against the exact request/view and
compiles supported candidates into actual Neo4j/Fuseki programs. Correlated
URI tuples preserve all path positions; declared functional scalar constraints
are checked on reached resources before filtering. Missing entity bindings,
unsupported constructs, invalid/multivalued scalar data and overflow fail
explicitly. No backend or model call repairs a missing entity automatically.

Actual controlled recording/track/release cases on the retained first shard:
string track number `"1"` gives one release; `"2"` gives empty; no scalar gives
the same release. Type-constrained track queries give one `music.release_track`
and no `book.book`. All five agree with independent full-Fuseki and Arrow
evaluation. An explicit numeric `1` against the string field fails before
literal filtering/baseline. The source, stores, frozen catalog, pending inline18
package and model parameters are unchanged. These are controlled fixtures,
not real LLM predictions or a comparative performance result.

The historical 3796877 source still hashes to f207a5d4…18. All 18 questions and
49 raw candidate outcomes are retained: 38 candidate grounding failures,
7 shared grounding failures, and 4 typed/grounded survivors with no positive
entity equality. Zero candidates are prepared under the explicit anchored goal.
This does not replace old semantic metrics or imply Freebase lacks the answers.
Durable receipts:
`experiments/artifacts/d203_historical_candidate_execution_20260910.json` and
`experiments/artifacts/d203_native_candidate_execution_20260910.json`.

Focused: 268 passed / 1 skipped in 2.61s (45 new offline tests). Harness and
21 examples pass, 22/22 entrypoints. Both owned native runs finished and stopped
normally, no SIGKILL: session 25261 and 9851, roots
`/Users/anthonyche/xgap-data/d203-native-candidates-20260910` and
`/Users/anthonyche/xgap-data/d203-native-types-20260910`. Source/example sessions
79649/76062 finished. No native data reload or catalog construction occurred.
No test/example/native process remains from this milestone.
Next: real generated anchored answers; the original fixed-v1 CWRU inline18
handoff subsequently became job 3799513 (see current D204 state above).
An optional new anchor feedback
profile is not part of D203 and must not silently alter that pending protocol.

## D202 accepted predecessor

D202 has completed **local software and real Freebase answer acceptance**. See
`docs/report/freebase_native_answer_bridge_v1.md`. The exact Neo4j 5.26.30 and
Fuseki 5.6.0 archives ran on installed Java 21.0.10 in an explicitly local
development environment. No CWRU gate or Java-17 contract changed. The full
D201 first-shard snapshot was loaded once: 3,247,670 occurrences became
3,233,752 distinct Fuseki facts and 541,675 Neo4j resource edges; independent
Arrow grouping confirms both distinct counts (13,918 input duplicates).

The typed query for English names of `type.property` resources returned
**103 identical entity/name pairs** from the actual federated plan, full-Fuseki
baseline and independent Arrow source evaluation. The new opt-in SPARQL IRI
VALUES boundary makes coordinator bindings effective in Fuseki. This is a
typed development query on a partial source, not NL/GrailQA accuracy.
One observation: federated 204.83 ms / two calls versus baseline 16.76 ms /
one call, different timing boundaries and baseline-after-federation cache
order; no speedup claim. Actual output rows encode as 9,044 + 17,924 bytes.

Focused: **241 passed / 2 skipped**; 30 new offline tests plus a live-gated test.
Harness + 19 existing acceptance examples pass. Full regression completed in
original session 43688: **2,782 passed / 38 skipped in 596.81s**, log
`/tmp/xgap-d202-full.log`. Do not restart any of these successful checks.
Native session 37809 completed exit 0, both services stopped without SIGKILL.
Source-query session 90335, distinct-count session 80344 and example session
64526 all completed successfully. No backend or source-build process remains.
Native output/data: `/Users/anthonyche/xgap-data/d202-local-native-20260910-diagnostic2`.
Source answer: `/Users/anthonyche/xgap-data/d202-source-query-20260910.json`.
Archives: `/Users/anthonyche/xgap-data/native-cache` (now present and verified).
The earlier local attempt 68937 failed before service startup because of the
Fuseki help CLI's explicit TerminationException/exit 1; its output is retained.
The corrected help validator passed in diagnostic2; no download/load retry.

Two additional declared book/person queries reused the same databases without
loading data again. Actual resource-match/final-name counts are 7/6 books and
2,234/202 people; all answers equal the full-Fuseki baseline and independent
Arrow source evaluation. The English-name requirement is enforced within this
partial source. Native session 37587 and source-reference session 87038 both
completed; services again shut down normally. No running handle remains.
Outputs: `/Users/anthonyche/xgap-data/d202-domain-queries-20260910`.
Durable receipt/all three answer sets:
`experiments/artifacts/d202_native_freebase_answers_20260910.json`.
Producer source hashes in that receipt remained unchanged through acceptance.
The local D201 commit 61923b6 was also verified at the remote branch head before
D202 began. The document inventory now records 64 full / 7 selected / 10 pending
Markdown reviews; the historical logical-lowering report was fully read while
the regression ran. Do not claim all indexed historical text is fully reviewed.

Next after D202 acceptance: inference-candidate-to-execution lowering and
actual end-to-end model answers. Preserve the existing typed data/mappings,
do not repeat passed exports/loads or substitute catalog/audit work. The
existing fixed-v1 inline18 CWRU package still awaits a returned job ID.

## D201 accepted predecessor

D201 local software and one-shard data acceptance is complete: typed Freebase fact snapshots and executable answer
integration. Scope/acceptance: `docs/report/freebase_typed_fact_snapshot_v1.md`.
The fact reader/exporter, tests and `examples/freebase_typed_fact_demo.py`
preserve all six archival columns and RDF term identity,
consume complete selected shards under finite budgets, and emit reusable
N-Triples parts. Old catalog/source behavior and frozen model inputs are intact.
Focused validation: **203 passed, 1 live skip in 4.47s**, including 52 new tests
and an actual Parquet → exported parts → HTTP loader → RDFLib engine → compiled
numeric-filter query → typed answer integration. The new offline demo passes;
its data is synthetic. Full regression completed in original session 67395:
**2752 passed, 37 skipped in 609.22s**. Harness and all 19 acceptance examples
also pass. Logs: `/tmp/xgap-d201-full.log`, `/tmp/xgap-d201-focused.log`,
`/tmp/xgap-d201-examples.log`. No running test/export/verification handle remains
from D201. Do not restart any of these successful checks without a new reason.
Durable receipt: `experiments/artifacts/d201_typed_fact_snapshot_20260910.json`.

The first frozen archival shard was downloaded once and verified at its original
SHA-256 `f1b21a5869da41938818a3f0f2ef2ead92fd5df978c2d5bf6fbaad31d3f650b1`:
14,984,726 bytes, 3,247,670 rows, five row groups. It was selected as the first
inventory entry before inspecting its contents, without questions/references.
Actual export completed successfully in original session 15621; do not rerun.
Log: `/tmp/xgap-d201-real-shard.log`. It emitted **3,247,670 occurrences,
420,940,219 bytes in 13 parts, in 98.57s**, with 125,272,064 bytes peak process
RSS (macOS observation). Kinds: 541,677 URI objects, 2,603,948 language literals
and 102,045 other typed/string literals. These are one local partial-source
construction observation, not comparative performance or query quality.
Source/output/plan receipts are under
`/private/var/folders/78/2hb19nqj0jv_l0vgmp084ht80000gn/T/xgap-d201-source-b2ymubis`.
The build uses all rows of this one shard, 16,384-row batches, 32 MiB parts and
a 1 GiB output ceiling. This is a partial source-data experiment, not a model,
real-backend answer, complete-Freebase or paper measurement. The source download
and completed demo must not be repeated just because this task continues.
Independent verification v1 completed all 13 parts/counts but failed its final
ordered term digest. The first language-literal diagnosis showed a verifier
representation bug: RDFLib's language literals expose `.datatype=None`, which
the ad-hoc verifier wrongly treated as xsd:string instead of implicit
rdf:langString. Source values, language and exported data agree. The failed
script/log and diagnosis are retained; neither exporter nor source was changed.
Corrected `verify_export_v2.py` completed successfully in session 35115; log
`/tmp/xgap-d201-independent-source-v2.log` and `independent_verification_v2.json`
were inspected. All 3,247,670 ordered terms agree at digest
`96aca67e31c1254387580000abfd21ef5dd163b84553f3eb6e04dfe9c4c66c78`.
Actual literals include 1,681 xsd:date, 6,089 xsd:gYear and 2,760 xsd:gYearMonth
values, plus 91,515 strings and 2,603,948 language literals. Verification took
57.79s alongside the full regression; no model/backend was called. Do not
rerun either the export or successful independent verification.

At D201 completion the next gate was: connect typed fact data to actual backend loading, dataset-owned term
mapping, generated query execution and cross-backend answers. Date/gYear/
gYearMonth terms are preserved but require their own comparison semantics;
the successful compiled query test uses integer years. Do not promote that
fixture into a claim of date-aware real Freebase answers. The inline18 CWRU
package still has no returned job ID, and no remote submission was attempted.
The D201 Java inventory showed Temurin 25 and Homebrew OpenJDK/21, but no known
Java 17 installation. The accepted native lock requires Java 17, Neo4j 5.26.30
and Fuseki 5.6.0. Read the actual lock and locate/retrieve exact local runtimes
before trying a separate local service experiment; never fabricate a Slurm
allocation or label a local run as CWRU. No service was started in D201.

D200 local software acceptance is complete: read-only reconstruction of the
guarded inline development run, including source/context, provider, semantic,
token/lifecycle and evaluation layers. See
`docs/report/grailqa_guarded_whole_run_evidence_v1.md`. D199 fixes v1 as the
control catalog; no actual new model run has been measured or admitted.

The implementation reconstructs complete actual offline-runner fixtures and
passes **184 focused tests in 17.39s**. Full regression completed in its
original exec session 59949: **2700 passed, 37 skipped in 625.92s**. Do not
restart it. The harness and all 19 acceptance examples pass. Receipt:
`experiments/artifacts/d200_guarded_whole_evidence_local_20260910.json`.
The narrow environment fix accepts numeric JSON 0/1 versus the bundle's
normalized floats while rejecting booleans; frozen specs are intact.
Accepted producer **6b32b973d4fd1a979b714570d3edcd2e684c1b07** is committed
and successfully pushed to the existing remote branch. The working tree was
clean after the commit. No source changed after the successful full suite.

The exact-commit remote operator package and one-step instructions are in
`docs/report/grailqa_inline18_cwru_handoff_20260910.md`. The local ZIP is ready,
but has not been uploaded or executed. It fixes v1, preserves prelaunch catalog
and tokenizer pins, submits once to an isolated checkout, then supports a
separate post-completion D200 reconstruction. Server-side upload/start has been
requested because both browser control and the one SSH route are unavailable.

User steering (September 10): explain XGAP versus graph-guided RAG, identify
which pipeline stage the catalog serves, and stop treating catalog work as the
whole system. After D200 acceptance, prioritize the fixed-v1 real inline18
experiment and actual federated answers. Metadata-index reuse and entity
coverage diagnosis remain separate, bounded work; do not repeat the same scan.

During the full suite, dedicated OnDemand shell tabs 366873210 (hpc5) and
366873213 (hpc7) appeared, but browser control timed out before any server
command was sent. No job was submitted or remote file written. CUA resets can
renumber browsers: most recent inventory was Chrome browser 1 and in-app
browser 2, not their earlier IDs. The new terminal tabs lack providerTabId in
the latest inventory; do not assume they are controllable. The user-owned
366872568 terminal still has a providerTabId and hpc8 title, but avoid typing
into it while the user is active. The earlier file-editor route remains a
separate read-only fallback. Native foreground typing remains unsuitable.
The subsequent read of existing file tab 366873192 also timed out before
returning any page content. This is a browser-control failure, not evidence of
expired authentication. No new remote action has been attempted. Prepare the
exact-commit runnable handoff and continue independent answer-execution work;
do not keep creating tabs or repeat unchanged catalog/audit work.
The alternate provider-ID lookup returned tab-not-found. A single strict,
noninteractive SSH connection to Pioneer port 22 timed out before any remote
command ran. No authentication setting was changed or credential requested.

Concrete next answer-chain gap: `freebase_sources.parquet_row_to_triple`
intentionally drops plain/datatype-bearing literals for catalog compatibility.
It cannot serve unchanged as the fact reader for dates/numeric filters. Build
the target-data path with full RDF term identity and independent answer checks;
do not change the old catalog parser, derive facts from gold, or substitute
another catalog/audit cycle. The D200 and handoff turn is progress: full
acceptance completed, source committed/pushed, exact runnable package prepared,
and the remaining remote-control and typed-fact gaps were directly observed.

D199 / H1 catalog comparison observation is complete. Job **3796988** finished
successfully; the actual report has **zero coverage gains and zero losses** in
all 15 stage/component cells. Both catalogs retain joint availability 10/18,
Top-20 joint retrieval 6/18, and deployed-prompt joint reachability 5/18.
All 18 entity ID lists, including order, are identical at all three stages.
Launch/log/status/report identities agree; all 15 counts were reconstructed
from the report's per-query rows. This is a real development observation,
not a fresh whole-run/source audit. The full report was read in the browser
session; only a compact derived receipt is durable locally. See
`docs/report/grailqa_catalog_comparison_3796988.md` and its linked receipt.
No executable source changed or full regression was repeated in this observation.

D198 adds read-only admission of the complete retained inline provider history:
all materializations, typed/grounded feedback, exact repair payloads, token
receipt and transport order, raw/consumed responses, invocation copies and
query state seals. This is a provider evidence component, **not whole-run
admission**, semantic accuracy, recomputed token counts, or server identity.
See `docs/report/grailqa_inline_evidence_v1.md`.
Focused regression: **215 passed in 3.13 seconds** (41 new tests).
Harness + all 19 acceptance examples pass. Full offline regression: **2587
passed, 37 skipped in 596.33 seconds**. D198 local software acceptance is complete.
Evidence: `experiments/artifacts/d198_inline_evidence_local_20260909.json`;
full log: `/tmp/xgap-inline-evidence-20260909/full-regression.log`.
The final handoff is `docs/report/xgap_implementation_report_20260909_evening.md`.
The scheduled recovery has now occurred.

D197 / H3 software acceptance is complete: inline slot annotations are
materialized into the existing guarded semantic pipeline, with original/derived
response evidence and deterministic replay. See
`docs/report/grailqa_inline_grounding_v1.md` and
`experiments/artifacts/d197_inline_grounding_local_20260909.json`.
Focused regression: **297 passed in 2.28 seconds**. Final full regression:
**2546 passed, 37 skipped in 608.62 seconds**. The harness check and all 19
acceptance examples pass. Actual Qwen schema acceptance, token fit and semantic
effectiveness remain unmeasured; H3's empirical comparison is still open.

The first full attempt was 2545 passed / 1 failed / 37 skipped. A historical
review test compared its frozen provider hash to later source. The test now
reads the original source from that review's declared commit, preserving every
old artifact/hash. The full suite was rerun after this test-only correction.
Do not repeat successful acceptance without a new code change or concern.

Prior completed milestone, commit `13dd4ba`: D196 / H2 preserves RDF term and resource identity through explicitly selected
native compilation, HTTP execution, runtime fragment wiring, and answer projection.
Implementation and 153 focused tests pass (one live gate skipped).
Full regression: **2503 passed, 37 skipped in 604.92 seconds**.
The harness check and all 19 acceptance examples also pass.
The new live Fuseki test is explicitly gated and not yet measured.

Current full regression log: `/tmp/xgap-inline-evidence-20260909/full-regression.log`.
Python with pytest 9.0.2 / RDFLib 7.1.4:
`/tmp/xgap-directed-tests.qU2YfW/venv/bin/python`.

## Remote state

OnDemand is open in Chrome at
`https://ondemand-pioneer.case.edu/pun/sys/shell/ssh/pioneer.case.edu`.
The user returned a fresh scheduler record for **3796988: COMPLETED, 0:0,
03:56:26**, start `2026-09-09T04:35:55`, end `2026-09-09T08:32:21` in the
scheduler's unverified time zone. This record was also read in the terminal.
Its log is
`/home/hxc859/XGAP-m15-465e2e2/slurm-xgap-grailqa-catalog-compare-3796988.out`;
the final five-line log was read through the portal editor and reports CLI
success with the same comparison hash as the status and report.
The job belongs to the previous e39b98e CPU catalog comparison and is terminal.
Keep its outputs intact. No new remote job has been submitted by this task.
There is no local SSH config. Native browser input can be delayed and drops
some special characters; do not send compound or state-changing commands
through that route until exact input is verified. Read-only attempts produced
two harmless `scontrol` syntax errors, not a change to the running job.

The restored login now works through a fresh extension-backed file tab. Raw
file links return Chrome `ERR_BLOCKED_BY_CLIENT`; the portal's ordinary Edit
view exposes file contents. Read/select/copy only, never Save. Its Save button
remained disabled after copying. Use a separate task tab, because the user may
navigate the shared tab during other work. Native foreground terminal input
remains unverified; do not type into a user-changing window or infer execution.
Do not treat retained screen text as a newly executed scheduler observation.

## Next actions

1. Continue the document reading inventory; long historical material is
   indexed but not all paragraphs have been reviewed. All three known source
   PDFs have now been read in full, with selected figures/formulas checked;
   proof verification and experiment reproduction are separate. Markdown
   progress is 63 full / 7 selected sections / 11 detailed reviews pending.
2. Preserve the 3796988 negative comparison. Do not repeat this rebuild or a
   GPU comparison of unchanged candidate sets. For inline-interface development,
   keep the old v1 catalog fixed; diagnose entity mention/alias/selection-rank
   exclusions separately from retrieval/prompt truncation, without gold-fed data.
3. Extend D198's provider evidence component to independent whole-run admission
   for the new materialized-response contract: producer/spec/population,
   catalog/retrieval, environment/lifecycle, tokenizer parity, metrics and gold
   isolation still need their complete evidence chain. Keep the new inline bundle/spec separate.
   Establish vLLM schema compatibility and actual request fit with the existing
   bounded probes while holding the v1 catalog fixed. No running job was found
   for this completed comparison; retain exact producer checkouts and use the
   existing staging/run authority before any new bounded experiment.
4. Prepare a real two-engine answer admission over inference-owned data.
   Current typed-row results are not full GrailQA execution or accuracy.

## Continuation

Existing automation `xgap` was updated, not duplicated, and has returned to
hourly bounded cycles. Stay quiet without meaningful change. The broad goal
remains in progress; the overnight pause is complete.

## Persistent rules

Never use gold to construct retrieval/deployment data. Keep all evaluation
denominators and failed records. Do not rerun the accepted FinBench campaign,
change its population, or claim independent instance-memory gains from the
recorded fixed-route tie. External failures are observations without silent
retry. Ask the user only for unavailable credentials/network/server action,
external artifacts, or a material scientific decision; routine authorized
implementation and testing continue autonomously.
