# Bounded core and evaluation interface freeze — 2026-09-12

## Subsequent scope clarification: financial queries

The accepted bounded-core evidence below does not prove ordinary-entry support for
the historical FinBench templates. Subsequent integration added edge Match and
field/timestamp comparisons: three financial gold programs now pass ordinary
estimated planning and selected execution on split native Neo4j/Fuseki tiny data.
See [the deterministic evidence](financial_binding_20260912.md). Four independent
native endpoint-bind plans now pass, with old28 observations reused and a new
32-sample model frozen; all six candidates per financial family are estimable.
[Coverage evidence](edge_bind_training_20260912.md) does not establish ranking or
speedup. Financial NL-only profile publication is now implemented; the first real
request failed Interpretation before grounding/execution. V2 also failed parameter
admission; v3 passed syntax and entity grounding but failed source compilation on
identity/property alias collision. All failures are preserved. Next implement a
compact intent lowerer to derive the existing DAG deterministically; it is not
implemented yet. [Financial NL evidence](financial_nl_20260912.md). Financial NL success and
real evaluation remain required. Do not call the whole system complete from the
earlier small-profile audit.

## Original bounded-core assessment

The approved bounded research backbone is implemented and has controlled and
tiny native integration evidence. The reusable per-request evaluation interface
is now implemented and checked offline. This is sufficient to move to experiment
plan discussion; it is not a claim that paper evaluation, external comparators,
estimator ranking quality or an accuracy/latency advantage are finished.

## Requirement-to-evidence audit

| Requirement | Implemented behavior and evidence | Remaining evaluation boundary |
|---|---|---|
| Ordinary NL, one final answer | Shared `run_question` entry; actual original NL + reusable schema → model → grounding → estimates → selected execution → independent exact answer at6833e19. [Native record](one_shot_split_20260912.md). | One development-exposed split-source question, with a preserved earlier Interpretation failure; not held-out accuracy. |
| Precision and performance | Same core, versioned K3/K1 defaults, different local information budgets and quality preferences. Both controlled slices passed; guided precision has an actual answer, and NL-only performance has the split-source answer. [Core](one_shot_core_20260912.md), [guided native](one_shot_native_20260912.md). | No paired real-NL mode comparison yet. Precision is a policy name, not a correctness guarantee. |
| Bounded semantics and Interpretation | Existing admitted Match/Traverse/Filter/Project/Join/Union/Aggregate/OrderLimit/Align forms, up to64 operators and finite path-expansion work<=4096. Candidate cap<=8; typed constraints, errors and output admission retained. | Backend/strategy capabilities further restrict combinations. No universal query language or unbounded path guarantee. |
| Information acquisition | Frozen catalog, optional local ontology fallback, bounded holes/options and visible truncation. Predicted bindings remain non-authoritative. Four actual catalog lookups in the split-source slice. | This version uses fixed mode budgets and local evidence; no learned adaptive information policy or calibrated confidence claim. |
| Actual federated strategies | Legal coordinator versus entity-bind DAGs; actual bound execution in guided precision and required Neo4j/Fuseki contributions in NL-only performance. | Single-change placement/rewrite neighborhood, not arbitrary join-order optimization. Ordinary split run executed only coordinator. |
| Frozen estimator | Actual-plan backend/workload features,28 tiny offline training plans, frozen weights and serving statistics, source/version checking and explicit transfer uncertainty. [Evidence](work_estimator_native_20260912.md). | Useful relative ordering is the target. Current adapter outputs ms; rank-only is not implemented and is not a prerequisite. Ranking, regret and generalization remain unmeasured. |
| Ptime estimated selection | For L total local options, P<=1+sum(k_i-1) placements and J joins, at most P(1+2J) physical candidates per interpretation. Compile/estimate and exact argmin over admitted estimates, without executing alternatives. [Contract](../decisions/one_shot_modes_v1.md). | No unconditional actual-latency approximation guarantee. Conditional2η regret requires a uniform numerical error bound in this domain; ranking alone does not imply it. |
| One-shot cost/accounting | At most one model request, one final plan; zero online probe/fit/automatic retry. Offline preparation stays separate. Actual tokens, calls, failures and logical exchange bytes retained. | LLM/native execution is external to the planner's Ptime proof. Unknown usage stays unknown; logical bytes are not wire bytes. |
| Dataset-independent execution records | New frozen profile, request, durable result/receipt, exact request/query replay, separate post-seal answer scoring. Nine unique new-risk cases pass; CLI preflight passes without calls. [Interface contract](../decisions/one_shot_evaluation_interface_v1.md). | Wrapper has offline evidence, not a fresh native benchmark. Neo4j/Fuseki clients registered; live data snapshot identity is a deployment assertion. |

The physical domain bound and conditional guarantee are research scope, not
promises about plans outside the domain. Current default max physical candidates
is256; an over-budget domain is rejected before construction. Existing finite
budgets and declared unsupported results remain visible. Do not expand semantics,
replace the estimator or repeat successful runs merely to make the system more
general before defining the paper experiments.

## New interface: what changed

`src/xgap/experiments/one_shot_profile.py` reads a pinned JSON dataset/source/schema/
backend/catalog/estimator profile with both mode policies and model/prompt identities.
It checks hashes, source snapshots and mode consistency before any external call.
Credentials are environment references. The runner does not build a catalog, fit a
model, load a dataset, start services or discover endpoints.

`src/xgap/experiments/one_shot_records.py` invokes the existing core once and writes
input, intent, provider record, actual backend artifacts/responses, result and
terminal receipt. Known calls/tokens survive a failed result seal; incomplete
accounting is unknown. Complete failures remain scoreable when request identity
is available. Replay must match the original provider/prompt, request and exact
backend artifacts. Its network calls are zero and its timings are labeled local
replay. A converted old full-query result is usable for replay; an old bind result
without its actual substituted native queries is explicitly insufficient.

Scoring is a separate invocation after the result seal. The reference specifies
dataset/question identity, normalized JSON rows, and whether order matters. EM is
order-aware when declared; row F1 uses multiplicity. Failed execution scores zero,
including against empty expected rows. This is not general semantic equivalence.
Population/exposure metadata is retained but excluded from the model context.

`scripts/run_one_shot_record.py run` defaults to preflight, with explicit execute
and replay operations. `evaluate` only reads sealed output and an independent
reference. There is no hidden batch loop or retry. See the dedicated
[usage and boundaries](../decisions/one_shot_evaluation_interface_v1.md#usage).

## Focused verification, with no new live runs

The nine unique new cases cover both-mode preflight, successful and failed saved
replay, post-seal scoring, source/mode/file drift, model/prompt identity drift,
changed request/native query refusal, and preservation of known usage on seal
failure. Network connections are disabled in these tests. Synthetic calls/tokens
in the persistence-failure test are accounting fixtures, not new model results.

First run:7 pass/1 fail in0.53s. The failing mock omitted provider response metadata;
the existing admission correctly refused it. Correcting that fixture yielded1
pass in0.26s. Review then corrected a drift test's relative path and added explicit
provider identity checking; only six affected/new cases ran, all passed in0.41s.
Thus nine distinct cases have passing evidence; the two rerun sets are not extra
independent tests. Tool chunks:5e9d48,df33d0,e72ebe. No accepted older suite was rerun.

The one CLI preflight exited0 (`4fbd31`), status `preflight_passed`, zero model,
backend, training and fit calls. Its endpoint addresses are deliberately inactive
local placeholders; they are for preflight/replay, not a live deployment profile.
Artifacts: `/Users/anthonyche/xgap-data/one-shot-profile-interface-20260912`.
The machine-readable [milestone receipt](../../experiments/artifacts/one_shot_profile_interface_20260912.json)
pins the prepared files and records this scope. No performance result was produced.

## Next: agree on the evaluation protocol

Prepare16–20 proposed figures, each with RQ, X, Y, population, cost boundary and
comparable external methods in the same plot. Separate end-to-end answer quality,
online efficiency, bounded planner/estimator quality, scalability, Pareto tradeoffs
and later ablations. Verify external method implementations and compatibility from
primary sources before calling them SOTA baselines; internal variants alone are
not sufficient. Freeze the dataset/split/reference and cost rules before campaigns.

Remaining work is paper-specific: benchmark profiles and references, external
method adapters, independent offline ranking references, cohort aggregation,
approved repetitions/scale settings and final plots. The current record limit is
16MiB per pinned file; large-result use requires an explicit result contract.
The runner does not prove loaded DB contents, normalize all scalar conventions,
or impose a hard global wall-clock deadline. Record/persistence overhead and
separate one-time costs must be included under the agreed measurement boundary.

Retain old FinBench paid-selection negative results and all populations/failures;
they are not new dual-mode results. No action on remote3804210. No new native/model
runs, calibration, baseline, ablation or scale campaign is started by this freeze.
The core delivery target remainsSep14 17:00 Beijing and real-results targetSep18;
the overall Goal stays active until the research objective is actually achieved.
