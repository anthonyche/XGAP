# T2-C: model adapter and five-question remote connectivity entry

2026-09-11; base local bea9321. Software interface accepted: focused, native and broad gates passed.
Real Qwen responses remain unmeasured.

One bounded OpenAI-compatible chat response now enters the same run_question
validator, frozen catalog, semantic binding, planner and execution path. The
provider preserves explicit hard constraints and entity-resolution authority.
It uses the existing pinned local chat-token counter before dispatch and never
repairs or retries. Missing credentials or an oversized request causes zero
model calls; a dispatched timeout or invalid response retains its actual call
count, reported token usage and safe request/response provenance.

Unknown or inconsistent token usage is explicitly unavailable. The numerical
token fields then contain zero *known reported* tokens, not a claim of a free
call; interpretation_token_usage_complete is false. Offline replay records zero
new calls/tokens and keeps historical usage and its availability separately.
Raw malformed model content can be replayed without asking the model again.

The tiny model entry sends only B01–B05 NL, prepared caller requirements and
the existing frozen bundle/source versions. It does not send expected rows,
gold programs, target queries or physical plans. Its language prompt explains
the existing syntax needed for these questions, with no per-question solution.
Prepared structured requirements and the five development questions bound this
connectivity check; it is not a general NL accuracy measurement.

| Gate | Result |
|---|---|
| Adapter, question, token-budget and legacy provider checks |157 passed,7.17s |
| Adapter, question, execution and GPU-profile checks |114 passed,11.40s |
| Actual loopback HTTP transport |One controlled response through normal question execution; no true model |
| Real Neo4j5.26.30/Fuseki5.6.0 with recorded controlled input |5/5 programs,18/18 candidate answers,10/10 independent targets and permanent slice correct |
| Broad offline acceptance |Exit0:3421 passed/38 skipped in676.02s; all24 harness/example entrypoints pass |

Native record: `/Users/anthonyche/xgap-data/t2c-native-recorded-interpretation-20260911/result.json`.
All35 native source hashes match current source; both services stopped with
SIGTERM without KILL. The native inputs were recorded templates, not Qwen output.
The independent targets, old graph, frozen catalog and gold remain unchanged.
The loopback test exercises HTTP and the adapter; native replay exercises the
transfer seam. Neither substitutes for a healthy GPU and an actual model answer.

Remote entry: scripts/slurm/cwru_toy_model.sbatch. It requires a clean exact
commit and Slurm allocation, then checks all five exact token budgets, verifies
GPU health and the existing frozen environment, starts Qwen3-32B BF16, waits for
the owned service, and records at most five generations. It reserves8192 input
and4096 output tokens within12288 context, with120s per generation and1800s
startup readiness; the job limit is1h, overriding the existing deployment
contract's4h default. H100 uses the existing explicit single-card health profile;
the accepted two-L40S profile remains available. Exclude gput069. There is no
generic extra smoke generation and no catalog build or large-data runner.

The model-only phase deliberately needs no database installation on the GPU
node. Return the small model-recordings directory to the existing native harness
using --agentic-semantic --interpretation-recordings to execute those exact
responses on the same tiny graph. Transfer-separated timings are diagnostics,
not a colocated end-to-end benchmark latency claim. True model quality and a
fully connected live deployment remain pending until observed.

No remote job was submitted by this milestone. The user's scheduler test IDs
3803924/3803925 remain estimates, not jobs. The prior bea9321 push failed because
the proxy closed its connection; it was not retried. A new offline bundle can
transfer the accepted source without GitHub access. Follow the mandatory
[tiny-first deadline plan](../experiment_delivery_20260918.md); quick development
must pass before running large datasets on the server.
