# P1: polynomial placement implementation and its first negative result

2026-09-11. Basec77c08c plus the source hashes in the accompanying receipt.
**Implementation and bounded toy execution verified; search-quality follow-up
required.** This is development/model evidence, not a new real-data paper result.

## What changed

The ordinary question/binding/execution entry now prepares local source options
instead of materializing the Cartesian product. Match/Traverse compilation is
factored once per operator/backend. Local capability checks and output-schema
agreement precede assembly; a minimum-call baseline handles execution budgets.
At mostK representative assemblies obtain all native observation artifacts.

The selector uses independent local minima in an explicitly checked separable
subcase, otherwise two coordinate passes. A same-topology monotone relaxation
provides LB≤OPT_est≤U; the chosen estimate never exceeds the baseline. Topology
changes produce an explicit baseline-only guarantee. Bounds refer to the current
critical-path cost model, not actual latency or optimal agent information gathering.

Memory hashes the local problem and fragments, not an exponential candidate set.
Static priority uses the same local domain and still performs no observations.
The ordinary entry's old `max_candidates` keyword now limits local options; output
declares that unit. Direct `prepare_semantic_placements` uses `max_local_options`.
Existing explicit enumeration remains available to small oracles and legacy
specialized experiments, including candidate-answer validation after serving.

Compact path repetition is checked arithmetically against the documented4096
expansion-work profile before lowering; expressions are rejected, never clipped.
Existing native128-branch/64-edge bounds still apply. See
[the algorithm contract and proof assumptions](../decisions/planning_ptime_contract_v1.md).

## Verification selected by experimental risk

- Initial interface check:111 passed/1 failed in5.92s. The failed assertion
  assumed fresh observations always produce the same number of evaluated plans.
  It now checks an identical local domain and cold/warm consistency under the same
  snapshot; fresh observations may legitimately change the search path.
- Compiler/binding/capability/static/memory plus initial P1 checks:146 passed/1
  failed in6.69s. The new huge-repetition test used an invalid parser key; after
  correcting that fixture, the final22 P1 tests passed in0.62s. No remaining
  failure is attributed to that invalid fixture.
- Fifteen existing scoped semantic-DAG cases passed in5.74s after fragment factoring.
- Real owned Neo4j/Fuseki gate23560 exited0:5 cold+5 warm programs,18 candidate
  answer checks,10 independent native targets and the retained split-data slice
  passed. All38 recorded source hashes match. Both services shut down normally.
- No broad acceptance suite or large dataset run was launched.

Native cold runs used18 observations+9 selected executions; warm runs used0+9.
Additional candidate validation, references and retained slice are separate from
serving costs. Every warm run selected the same plan as its cold snapshot.

| Query | Local options | Complete plans scored | Model ratio certificate |
|---|---:|---:|---:|
| B01 | 4 | 4 | 1.0087 |
| B02 | 4 | 3 | 1.0393 |
| B03 | 4 | 3 | 1.0663 |
| B04 | 2 | 2 | 1.0116 |
| B05 | 4 | 4 | 1.0378 |

These are upper bounds relative to the estimated optimum under the checked
model assumptions. They do not establish1–7% proximity to real optimal runtime.

## P1 grid: polynomial work, but a poor heuristic case

The frozen grid ran15(m,k) cells, two estimate regimes and ten seeds:300 model
runs, including140 small exhaustive comparisons. All70 exact-branch oracle
comparisons matched optimum; every checked LB≤OPT≤U≤baseline inequality held.
No service, LLM or network call was used by the grid. Run1650 exited0.

The generated programs have **independent terminal source blocks**, and the
replicas are simulated configurations of the RDF compiler. They are not k live
endpoints, growing data graphs, or representative coupled join workloads.

| m × k | Product-domain upper bound | Local options | Max complete plans scored | Preparation ms | Median selection ms | Peak traced MiB |
|---|---:|---:|---:|---:|---:|---:|
| 2 × 2 | 4 | 4 | 4 | 2.87 | 2.00 | 0.25 |
| 8 × 8 | 16,777,216 | 64 | 113 | 90.38 | 78.25 | 2.09 |
| 32 × 8 | 79,228,162,514,264,337,593,543,950,336 | 256 | 449 | 1,146.19 | 1,243.40 | 23.07 |

Timing includes allocation tracing and is diagnostic CPU evidence. Oracle work
is outside the traced region. The full grid and metadata are retained; these
numbers cannot be presented as paper latency or a real-data scalability result.

**Negative result:** m=4,k=8,seed9,variable-row estimates selected63.936ms against
an oracle optimum10.096ms: **6.3328× model regret**. The reported lower bound7.936ms
gave an8.0565× ratio certificate, so the bound was valid but loose. The baseline
was94.522ms; improving that baseline does not mean the plan is near optimal.

The immediate issue is an overly conservative separability admission condition:
it requires equal remote row/width estimates even when a source is terminal and
has no downstream consumer whose cost depends on those estimates. Such programs
can be solved by independent source minima despite variable local rows. The
current implementation needlessly sends them through coordinate search, where
critical-path plateaus can yield a poor choice. This is not evidence of
NP-hardness, backend failure, or a need for larger datasets.

Next: preserve this negative run, replay this exact case without services, refine
the sufficient separability condition for terminal sources, and compare against
the same oracle. Check counterexamples with actual downstream consumers so the
condition is not loosened unsafely. Re-run only affected planned cells/branches;
do not repeat broad tests or native service gates merely because the analysis changed.

## Artifacts and remaining prototype work

- [Receipt and per-query certificates](../../experiments/artifacts/polynomial_planning_20260911.json)
- [Planner-grid CSV](../../experiments/artifacts/polynomial_planning_20260911.csv)
- Raw native record:`/Users/anthonyche/xgap-data/p1-native-20260911/result.json`
- Raw model grid:`/Users/anthonyche/xgap-data/p1-planner-grid-20260911/result.json`

The ordinary entry no longer depends on exponential placement enumeration. The
next quality correction remains part of P1; selective acquisition/replanning
integration, real-data/answer evaluation, actual model evidence and the paper
comparisons remain unfinished. Remote3804011 was not re-polled or resubmitted in
this step; its last user-observed state was PENDING. The September18 deadline and
small-data development rule remain in effect.
