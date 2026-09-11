# A1: ordinary-query refresh and reselection — 2026-09-11

The ordinary question → frozen resolution → P1 planning → native execution path
now supports one selective profile refresh and optional pre-execution reselection.
This closes a specific E2/E3 integration gap. The three modes execute different
actions through the same entry; they are not labels on an unchanged runner.

| Mode | Current profile calls | Execution calls | P1 selections | Backend | B04 gold | Observed question time |
|---|---:|---:|---:|---|---|---:|
| refresh_reselect | 1 | 1 | 2 | Fuseki | correct | 28.73ms |
| refresh_only | 1 | 1 | 1 | Neo4j | correct | 42.10ms |
| no_refresh | 0 | 1 | 1 | Neo4j | correct | 14.98ms |

These are **one tiny query, one fixed-order run per arm**, using explicitly
synthetic old cardinality/latency estimates and actual, unmodified current native
responses. They show correct mechanism execution and cost accounting. They are
not a real-workload speedup or causal performance comparison. In this observation,
no-refresh was fastest. A successful backend switch does not establish that the
information acquisition paid for itself. Preserve this result; the no-acquisition
baseline and total-cost objective remain necessary.

All arms share the identical historical table and retain its original acquisition
cost separately:2 calls,330.44ms. This cost is not added three times to current
query time or silently treated as free. The injected old table is explicitly
marked synthetic: Neo4j0ms/Fuseki1e-9ms, zero estimated rows and width1. The real
nonempty B04 observation challenges that table; this is a development intervention,
not a claim that those estimates were once true on the same frozen data.

The policy chooses one registered profile key from the initial plan using largest
historical elapsed time, with stable ties. This request rule is a heuristic,
without a proved information-value guarantee. The three modes require complete
warm history and fail before backend calls on missing/expired/incompatible inputs.
They never silently collect a full cold table. Memory stays read-only; a single
refresh cannot renew the whole table's TTL. A bare explicit snapshot reports
historical acquisition as unavailable. Failure retains one attempt with no retry.

Each selection/certificate keeps its own snapshot version. Refresh-only retains
the old decision and separately scores the executed plan under the updated table.
There are at most one current acquisition, two P1 selections, one final scoring
pass and one selected-plan execution. Local planning remains polynomial under
P1's declared input/model assumptions. This gives no universal approximation to
actual latency, optimal acquisition or cross-snapshot non-regression. Native
transport timeouts remain in force; the test harness additionally has a five-minute
outer limit and30-second server query limits. There is no invented policy timeout.

Verification:

- 60 affected existing memory/static checks pass in4.01s.
- 11 new refresh checks pass in0.71s, including the full B04 NL/gold chain,
  immutable JSONL history, admission/failure and per-snapshot accounting.
- One additional harness test passes in0.16s: a correct answer on the wrong
  backend must remain a failed mechanism check, preserve evidence and stop later
  arms. Review found and corrected premature success marking before live launch.
- Live Neo4j/Fuseki gate97715 exits0: one cold preparation query, three arms,
  two independent native reference queries and the retained two-engine slice
  pass. Total12 validation query calls, excluding setup/load/health checks.
  All40 recorded source hashes match. Owned Fuseki10831/Neo4j10801 stop normally.
- No broad suite, large dataset or LLM call. An initial default-interpreter run
  skipped10 cases for missing RDFLib; those skips were not accepted as evidence.

[Evidence receipt](../../experiments/artifacts/semantic_refresh_20260911.json),
[per-arm CSV](../../experiments/artifacts/semantic_refresh_20260911.csv), and raw
`/Users/anthonyche/xgap-data/a1-refresh-native-20260911/result.json` preserve the
actual observations and scope. The implementation contract is
[A1](../decisions/semantic_refresh_v1.md).

A1 is accepted, but the full prototype is unfinished. Execution-prefix adaptation
still needs a bridge from P1 to existing scheduler/probe/reuse primitives, with
executed placements fixed and a residual-cost/feasibility contract. The fixed
one-request policy also does not yet decide when acquisition is worth its cost.
Real-model LINK, real-data answer integration and frozen E1–E5 comparisons remain
pending. Remote3804011 was not queried or resubmitted in this step. Keep the
September18 deadline and toy-first development rule.
