# T3-A: static placement through the normal question entry

2026-09-11. Base: `73575c7834b5def377ace37df48693229c1d84a8`.
Status: **accepted** for this bounded software/tiny-native milestone.
This is a tiny development milestone, not a new real-data paper result.

The generic question entry previously obtained every unique source observation
unless a cost snapshot was supplied. A fixed physical placement baseline must
be able to avoid that acquisition cost, so that an experiment can test whether
cost-based selection pays for its observations. The specialized FinBench static
baselines already exist and retain their own frozen protocols.

## Implemented boundary

An explicit `static_backend_order` now flows through the same `run_question`,
binding, candidate enumeration, compiler and executor. It chooses only among
admitted, semantically equivalent placements, using backend priority in sorted
source-operator order, with plan ID as a deterministic tie breaker. It never
reads observations, measured timings, estimated costs or answers. Cost estimates
and snapshot identity remain unavailable. Default costed selection is unchanged.

Conflicting snapshot/static inputs, invalid priorities and different semantic
equivalence classes stop before backend dispatch. A selected-backend failure is
terminal; the baseline does not switch to a second backend after failure.
The original graph, gold cases, native reference queries, ontology, catalog,
algebra and compilers are unchanged. Frozen scope:
[static selection v1](../decisions/static_semantic_selection_v1.md).

## Verified evidence

Focused session 76409: **115 passed in 4.70 s**, exit 0. These include eight
composed semantic cases and five question/binding cases under both backend
orders, independent expected answers, unchanged candidate meanings, compiler
admission, error accounting, and a test that forbids observation/cost access.
In one controlled same-meaning case, default selection makes four observation
calls plus two execution calls; static placement makes zero plus two. This is
a call-accounting check, not a speedup estimate.

Real Neo4j/Fuseki native session 64202: exit 0; **5/5 question programs,
18/18 candidate answers, 10/10 independent native targets**, and the retained
two-engine split-data slice pass. The selected static order was Neo4j then Fuseki;
all five selected programs placed their source operators on Neo4j. Candidate
and independent-reference validation still exercised both engines. This is
not a claim that each selected static program required cross-engine execution.

| Query | Expected result | Planning observation calls | Selected execution calls |
|---|---|---:|---:|
| B01 | Person `c`, edge `e4` | 0 | 2 |
| B02 | Person `c`, edge `e2` | 0 | 2 |
| B03 | Empty answer | 0 | 2 |
| B04 | Person `a`, age 30 | 0 | 1 |
| B05 | Controlled identity clarification, then person `c`, edge `e2` | 0 | 2 |

The selected question executions used **9 backend calls** in total. The harness
separately used 25 calls for candidate validation, 10 for native references and
2 for the retained slice: 46 test-query calls, excluding service/data setup.
Do not count only the selected calls as total harness cost. Native timing
samples remain diagnostic; there is no randomized, controlled timing comparison.

Both owned native services stopped normally without escalation. Every recorded
native source hash matches the final source used for this gate. Final broad
acceptance finished in the original session 75266, exit 0: **3457 passed,
38 skipped in 680.07 s**, with all **24 harness/example entrypoints** passing.
All 38 final receipt source/test hashes match; no source or test edits after
broad launch. All handles are terminal. Log: `/tmp/xgap-t3a-static-acceptance.log`.

Evidence:
`experiments/artifacts/static_semantic_selection_20260911.json` and
`/Users/anthonyche/xgap-data/t3a-static-native-20260911/result.json`.

## Reproduction and remaining gate

Focused checks use `tests/test_static_semantic_selection.py`,
`tests/test_semantic_planning.py`, `tests/test_question_interpretation.py`, and
`tests/test_live_question_interpretation.py`. The new tests are also in the
existing toy development runner. The existing owned-native harness takes
`--agentic-semantic --static-backend-order neo4j fuseki`; the same option can
later be combined with `--interpretation-recordings` for recorded model responses.
Final broad validation uses the existing `scripts/run_acceptance.sh` entry.

The remote model producer remains **bc2bb67**. The local static selection change
does not require replacing its five-question package or altering model requests.
Actual model responses, their exact same-graph execution and frozen real-data
comparisons remain unverified. The cancelled H100 job 3803984 ran for zero time;
the authorized L40S replacement **3804011** is PENDING/Priority with no allocated
node and an estimated September 11 18:28:27 Asia/Shanghai start. This estimate
is not a reservation. The user executed and supplied all remote observations,
which are tracked separately in the remote submission receipt.
No large dataset or catalog build ran for this milestone. The September 18
deadline, all experiment denominators, and remaining EQ1–EQ5 obligations stand.
