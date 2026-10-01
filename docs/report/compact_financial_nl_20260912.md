# Actual compact financial NL boundary — 2026-09-12

At03314a9, the ordinary financial NL request completed through one actual
qwen3.8-27b response, deterministic compact lowering, frozen entity grounding,
estimated physical selection and one final execution on split Neo4j/Fuseki data.
Independent post-seal scoring returned ordered answer EM=1 and row-multiset F1=1.
This establishes the actual compact financial vertical slice. It is one exposed
development question, not held-out accuracy or a baseline efficiency comparison.

## Answer and semantics

The unchanged `datasets/financial_nl_tiny_v1/request.json` asks for direct transfers
from Alice-owned accounts into blocked company-owned accounts, within the inclusive
Jan1–Jan4 window, grouping by destination account and company business IDs.
Parallel transfers count separately, with all rows sorted by total descending and
company/account ascending. It supplies no gold operators or source assignments.

| company_id | account_id | total_amount |
|---|---|---:|
|1|2|66.0|
|1|3|9.0|

The model declared four node variables, three directed edges, the destination
blocked predicate, both timestamp bounds, SUM without DISTINCT, the requested
output aliases/order and limit=null. It also declared Alice as both a named entity
and `personName = Alice`. This redundant scalar restriction matches the frozen
snapshot but caused an extra property read; the raw model output was not edited.
No unrelated company-blocked condition was added. The compiler produced21
operators and9 source reads. Alice was catalog-bound to person_31 with
authoritative=false, preserving prediction provenance.

## Measured work and cost

| Quantity | Observed value |
|---|---:|
| Actual model calls |1|
| Reported input / output tokens |1928 /550|
| Provider work, including compact lowering |3032.615 ms|
| Compact lowering alone, already included above |2.536 ms|
| Frozen catalog load |1.735 ms|
| Grounding |0.916 ms|
| Physical planning and estimation |84.264 ms|
| Final execution tool, including durable source capture |234.327 ms|
| Core end-to-end online time |3374.613 ms|
| Wrapper preparation, separately recorded |13.905 ms|
| Final plans executed |1|
| Native query calls |9: Neo4j6, Fuseki3|
| Current-query probes / training / fits / retries |0 /0 /0 /0|

Six legal physical candidates received estimates within a construction bound of13.
The estimator selected `placement-0/coordinator` at20.334 ms. The alternative bind
plans were compiled/scored, never executed. This prediction does not establish
absolute timing accuracy, ranking correctness or regret: no actual candidate
oracle was measured, and final tool time includes capture/dispatch work. The
model-quality proxy0.9 is uncalibrated, not a90% correctness claim.

Offline preparation33.546 ms, owned service startup7325.827 ms and tiny load958.696 ms
are recorded separately. Loads comprised five Neo4j constraints, four node batches,
four relationship batches and one Fuseki RDF load. They are not hidden among the
nine final query calls. No new training, baseline request or large-data run occurred.

## Artifact and lifecycle audit

Root: `/Users/anthonyche/xgap-data/financial-nl-native-20260912-compact-v1`.
The immutable native receipt, ordinary request record, raw compact/provider response,
lowered program, selected plan, nine successful source observations and independent
score are retained. `audit.json` pins those artifacts and verifies every presealed
input unchanged. The6/3 source ledger exactly matches the recorded9 calls.

- Native receipt SHA-256:4e9d39fd1477cd177753a422d6302546e476573f13517e7e298124536a014763
- Request receipt SHA-256:aeac87aeb60c6b8b3ddc7c226c6c4a0c527d0db37f58e4a0f31476cc1cefacf8
- Interpretation recording SHA-256:f3dd6fd982a2b5147bbd13ee90bf778e2190b8f72cd3fc37a271cade08c899af
- Independent reference SHA-256:1e617d2be66bf93bfc372b14e4cc04388476fdb7ce45f1f231044bacb56a3691

Owned Neo4j PID44907 exited0 and Fuseki PID44952 exited143 after requested SIGTERM,
without forced kill. Both processes were independently confirmed absent afterward.
The credential was read without terminal echo and used only in process memory.
No remote GPU job was queried or modified.

Six provider integration checks passed in0.59s before this actual request. They
covered independent invalid-candidate handling, durable raw/lowered replay, budget
and unmappable-hard-constraint rejection, exact K1/K3 profile reconstruction and
the existing frozen estimator's compatibility with all three lowered financial
families. The earlier nine compact-lowering checks were not repeated.

## What this establishes and next work

The former repeated failure to generate intermediate columns and property dataflow
has an executable correction: the model expresses graph intent and deterministic
lowering manages those details. The financial ordinary-entry pipeline now has a
real answer. The prior v1/v2/v3 failures remain unchanged in
[their report](financial_nl_20260912.md); these four attempts share one exposed
question and must not be reported as four independent accuracy samples or a
controlled prompt/latency comparison.

Actual compact NL evidence currently covers the direct-transfer request in
performance mode. The temporal-path and risk-ranking meanings have independent
local lowering/execution and frozen-estimation evidence; their compact real-model
accuracy has not been measured. Precision K3 is wired and locally checked, with
earlier small-profile native evidence retained under its original scope. These
limits belong in evaluation, not a claim of universal semantic completeness.

Next freeze the approved real FinBench/RDF workload, independent references,
numeric equivalence and resource/cost/split contracts, using the now-working
ordinary recorded interface. Complete only necessary shared input adapters for
the unchanged runnable FedUP/FedX methods; preserve their failures. Do not repeat
this successful boundary, train for millisecond accuracy or start ablations before
the main evaluation cohort. Sep14 17:00 core and Sep18 real-results targets remain;
the overall research/evaluation Goal is still active.
