# T7: first frozen FinBench development pilot

The 72-hour app Goal is ACTIVE. Start: 2026-09-20 20:30 Asia/Shanghai;
delivery target: 2026-09-23 20:30. The approved three-dataset E1–E20 plan is
unchanged. This report closes one development pilot, not the formal evaluation.

## What actually ran

Pinned original FinBench SF0.1 CSV snapshot, real Neo4j + Fuseki, code
`48d5c6871dfa36469723ea36877060c0a412ce52`. Twenty-four distinct grounded
families: 12 live-NL cases and 12 controlled cases, each in Exact and Performance
(epsilon 0.5). Thus **24 questions / 48 method runs**, not 48 independent questions.
The controlled cases supply path depth as an initial public clue. Both modes get
the same clue; the full three-coordinate loss denominator remains fixed.

Selection was sealed before computing any reference answers: uniform accounts
within an outcome-independent pilot fold, then uniform windows and legal intents.
All intents/windows sharing an account stay in one pilot/formal fold. There is
only **one structural template**; no unseen-template generalization is claimed.
Reference answers come from an independent DFS over original CSV facts.

All 48 cells were sealed, with no automatic retry. Forty-seven answered and
matched their references. One Exact NL attempt hit the model provider's 60-second
timeout; it remains a failure in the full denominator. It is not a semantic
rejection or evidence that Performance systematically avoids service timeouts.
There were 24 model calls; controlled cases used zero. Remote token consumption
for the timed-out call is unknown, not zero, despite historical raw zero counters.
All owned source processes closed; no incomplete or unattempted cells remain.

## Observations, with their limits

|Track|Metric|Exact|Performance|
|---|---|---:|---:|
|NL, 12 cases|Correct / answered|11 / 11|12 / 12|
|NL, 11 common completed cases|Mean end-to-end seconds|30.690|30.450|
|NL, all 12 requests|Mean clarification calls|0.917|1.000|
|Controlled, 12 cases|Correct / answered|12 / 12|12 / 12|
|Controlled, 12 common completed cases|Mean processing seconds|19.615|19.656|
|Controlled, all 12 requests|Mean clarification calls|1.000|0.000|
|Controlled, all 12 requests|Mean backend transfer MiB|56.66|56.66|

The lower NL Exact clarification mean reflects its timeout before clarification,
not cheaper successful decisions. Both methods use one model call per NL request.
NL and controlled latencies have different starting points and are not mixed.
The paired latency-difference standard deviations were 1.162 s (NL) and 0.812 s
(controlled); this single pilot does not establish a latency advantage.

**23 of the 24 private reference answers are empty**; the one nonempty controlled
case contains one row and both modes return it. The high observed answer scores
therefore provide weak evidence about quality trade-offs. This is an observed
property of this frozen population, not grounds to remove or replace its cases.

All 47 executed queries passed the independent certificate check. Exact's largest
measured structured query loss was 0; Performance's was 0.5. This does not bound
answer discrepancy or establish a nontrivial quality frontier.

Controlled backend execution averages about 19.3 s, versus about 0.35 s planning.
Avoiding a local simulated clarification does not remove this execution cost.
Observed peak worker RSS was about 724 MiB and source-group RSS about 1.38 GiB,
within the declared sampled limits. These are sampled observations, not OS caps.

Post-seal inspection of the first selected plan found three unbound transfer-edge
reads with the same projected property but different output aliases. The frozen
toy-transfer estimator flags 28 features outside its training range: its 0.524 s
prediction accompanies 26.834 s actual execution. Absolute error alone does not
establish a ranking error, but calibration/relative ordering needs a development
check before formal use. Existing binding alternatives also reject several shared
chains. The saved diagnostic is `pilot-execution-diagnostic.json`; no alternative
plan was executed to choose an online winner.

## Immediate actions before formal freeze

1. Keep this pilot intact. Broaden the declared workload using independently
   specified supported query shapes; do not select test queries by method wins
   or answer existence. Report empty-answer frequency by family and template.
2. Audit broad source scans, repeated transfers and predicate/binding pushdown in
   the saved plans. Fix only demonstrated experiment blockers, with toy/replay
   checks and a separately labelled small real check. Do not retune from test data.
3. Freeze formal family sampling, repetitions, meaningful-effect target, resource
   caps and cache/order protocol after the workload and variance gate. This pilot
   alone cannot size the full structural workload or authorize a superiority claim.
4. Complete the unchanged external baseline and other datasets independently.
   ARUQULA's official Python dependencies currently fail on its pinned transitive
   dependency `litellm==1.37.19`; preserve this SETUP_ERROR while checking an exact
   official source artifact. No baseline prompt or algorithm has been altered.
5. Continue the approved matrix, then publish measured tables and figures with
   missing panels explicit. Freebase/FedShop admission, genuine source sharding
   and external comparisons are still unfinished, not implied by this pilot.

## Evidence and reproduction

Local root: `/Users/anthonyche/xgap-data/ch7-finbench-pilot-20260920-v1`.

|Artifact|SHA-256|
|---|---|
|`release/release.json`|`85e2d7e66c065a02510064054e828a99edaa43ec65095d38913f5059440d71d5`|
|`release/batch.json`|`c720f3c00cae2de2099bb5b2578e6029a1f6c97908df9dc14f71d343c971ae0c`|
|`run/invocations/0002/receipt.json`|`da2e56558fd5ef1a2c904c63aea226acd9bec886d4865f2305df4c76f5b68235`|
|`analysis-v2/summary.json`|`3ece8376b5af62d2faaa7d42b9302e180070017a653649da8cd9149b6033eaf5`|

`analysis-v2/metrics.csv` contains every planned cell; `summary.json` pins each
terminal, reference score, timing and query-loss record. Regenerate with
`scripts/analyze_chapter7_pilot.py --release-path <release/release.json>
--release-sha256 <above> --run <run> --output <new-analysis-directory>`.
This is offline analysis with zero model/backend calls. Two focused tests cover
failure denominators, paired timing exclusion, missing metrics and unattempted
cells; the analyzer also validated all real receipt hashes and source closure.

GitHub synchronization was attempted after local commit `06a7272`; both HTTPS API
and SSH port 443 timed out. The local commits are retained. Do not describe these
T7 changes as remotely published until a later push is verified. The same network
failure currently prevents fetching official baseline dependency artifacts.
