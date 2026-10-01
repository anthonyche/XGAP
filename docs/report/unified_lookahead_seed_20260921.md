# Unified lookahead: first implementation slice

2026-09-21. The user authorized starting the unified migration. This implements
the validation/online-controller foundation and a protected-seed vertical slice;
it does **not** complete the entire revised manuscript's action space.
Formal experiments and scheduled execution remain paused.

## Implemented

- `agent/unified_contract.py`: designated validation requirements, versioned
  direct observations, independent Lambda and rational interpretation-loss
  checking. A singleton remaining candidate does not satisfy missing validation.
  Fixed fields can also have explicit requirements at this contract layer.
- `agent/unified_lookahead.py`: fixed depth 1–4, separate action horizon,
  request-fixed max/expectation backups, every declared outcome including
  zero-probability outcomes, completion-aware leaves, resource reservations,
  no-progress probe suppression, execution ties and saved-recipe deadline fallback.
  Only one selected action has effects before replanning. Failed calls retain
  spend evidence; absent evidence is unknown, not zero.
- `agent/unified_family.py`: a polynomial completion recipe over the explicit
  family. Full disclosure followed by an already compiled seed is checked by
  scanning the family, not by constructing a horizon-H policy tree. Scoped
  confirmation still occurs when candidate uniqueness does not discharge a
  required validation. An epsilon-certified terminal may skip permitted fields.
- `api.answer_unified`: shares the existing proposal, paid scope authority,
  compiler and runtime. Mode labels are replaced by explicit settings. Historical
  `answer(..., mode=...)` behavior remains available and unchanged in scope.
- `scripts/check_unified_lookahead_native.py`: bounded three-case real-backend
  admission, using two final executions and a zero-call completion-budget rejection.

```python
from xgap.api import answer_unified
from xgap.agent.unified_family import UnifiedSettings
from xgap.agent.unified_lookahead import Limits

# Supply the existing public scope, private authority and frozen runtime inputs.
result = answer_unified(request, provider,
    settings=UnifiedSettings(epsilon='0', relaxable=(), limits=Limits(depth=1)),
    **runtime_options)
```

## Evidence and limits

Focused tests cover both starvation counterexamples, useful probes with sufficient
slack, fixed max/expectation behavior, zero-probability dead outcomes, unknown
resource bounds, no-progress retry keys, deadline fallback, actual-response
checking, direct authority and a complete portable SPARQL execution on the toy
graph. The changed public entry is also checked against its existing bounded
joint tests. No broad regression or old benchmark batch is run.

The new family admission prepares one protected seed per candidate independently
of terminal eligibility. It has known local capability declarations and **no
selected live metadata/probe or physical-transform actions yet**. The generic
solver admits their action types, but synthetic tests are not real-tool admission.
The family adapter does not invent a probability distribution; it currently uses
worst-case backup. The generic expectation path is separately tested.

The fallback depends on supported seeds for all remaining candidates unless an
eligible terminal already exists. Unsupported seeds remain in semantic support;
they are never removed to shrink the loss bound. This conservative admission may
fail despite another feasible completion; it reports missing completion evidence,
not mathematical infeasibility or global optimality.

`remote_calls` in this adapter means scheduler-level backend invocations. Seed
plans with bind nodes are rejected until their bound is separately admitted.
Backend result bytes and peak memory are unknown in the completion certificate;
configuring hard limits for those quantities rejects this admission instead of
using estimates as proofs. The native harness still has its own source response
limits and owned-service cleanup. Those guards do not prove request success.

The online resource ledger begins after common NL/scope initialization. Their
calls/tokens/latency remain separately measured in the shared API. Optional
planning deadlines are cooperative; domain callbacks must obey the documented
polynomial local-work contract. This is not hard real-time or arbitrary-memory
completion certification. Direct authority is implemented; registered inference
rules remain an explicit next-step interface, not an automatic singleton rule.

## Next integration work

1. Admit retained multi-plan pools and individual semantics-preserving physical
   transformations while protecting completion seeds.
2. Register actual metadata/statistics adapters, finite outcome categories and
   dependency/version-based cost invalidation in the same state loop.
3. Pin the new controller/settings in the durable batch worker and revise the
   evaluation release. Do not reuse old Exact/Performance method IDs for this code.

## Completed verification

40 distinct focused tests passed across incremental checks: 4 validation-contract,
15 lookahead/resource/failure-accounting, 8 new family/API, and 13 existing bounded
joint tests. The initial native harness missed the frozen request's schema field;
it failed before any case execution. Its failure receipt and complete service
closure are preserved. The corrected request was checked offline against that
frozen profile before starting a new, separately recorded admission.

The real native gate on code `d6adaa0` passed all three expected outcomes:

|Case|Outcome|Answer rows|Scope / clarification calls|Final plans|Observed backend HTTP requests|
|---|---|---:|---:|---:|---:|
|Strict validation, fixed-depth search|Correct independent reference|4|1 / 1|1|9|
|Zero optional-search time|Correct answer through saved completion|4|1 / 1|1|9|
|Zero remaining validation calls|`completion_witness_unavailable`|No answer|1 / 0|0|0|

Both executions use actual Neo4j and Fuseki over the same frozen eight-node
development input. No model calls, dataset builds, training, baseline runs or
current-query alternative-plan executions occurred. These are correctness and
interface results, not a speed comparison or formal Chapter 7 result. All owned
process groups were drained, services terminated and observers stopped. Frozen
source data and original evidence were retained.

Evidence roots:

- Successful gate: `/Users/anthonyche/xgap-data/unified-lookahead-seed-native-20260921-v2`.
  Receipt SHA-256: `405c7f310a22a0b186332a78df2218a5a9951bf195daf82c50e8c26173e17d14`.
- Preserved setup failure: `/Users/anthonyche/xgap-data/unified-lookahead-seed-native-20260921-v1`.
  Receipt SHA-256: `2f0ee77fd62d99bfeab1fff33ab17b0a945c4d3b9bc0accd9e9dbe1826b70e94`.
- Frozen prepared tiny stores: `/Users/anthonyche/xgap-data/native-campaign-boundary-20260913-v2/prepared.json`,
  SHA-256 `8f3c88515f52f8526faa4f9963a381ad1df1af7bf419f9bbdce0ec5e11648051`.
