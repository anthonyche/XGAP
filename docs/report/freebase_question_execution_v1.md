# D205: one bounded question-to-native-answer entry

Status: COMPLETE for software and controlled native acceptance on September 10,
2026. H4 remains open for fresh model-generated correct answers. This entry
connects existing catalog retrieval, the guarded provider, D203 grounding and
compilation, and the native runtime. It does not modify the queued inline18 run.

## Frozen scope and acceptance

Implement an explicit question API and development CLI, retain the exact
inference request and model evidence, refuse unresolved entity/interpretation
ambiguity, and execute a unique supported interpretation within finite budgets.
Separate serving from optional full-Fuseki verification. Preserve answers when
verification fails and preserve all generation/preparation failures. Add an
offline example and integration tests, then reuse the already loaded native
stores for controlled acceptance without rebuilding the catalog or facts.

Allowed changes: question orchestration, explicit execution options, immutable
JSON goal bindings, tests, example and documentation. No lower-level algebra,
frozen catalog/model/spec, remote runner, inference population, source facts or
legacy result changes. No automatic external retry or gold-derived binding.

## Implemented behavior

`answer_question` accepts a question record, injectable catalog/provider and
already configured Neo4j/Fuseki clients. Retrieval supplies the prompt view;
the exact request carries the caller's execution requirements into generation
and preparation. No visible entity produces an unavailable result; multiple
visible identities require explicit caller-owned positional bindings before
model invocation. Distinct structural candidate programs require clarification.
A valid unsupported sibling prevents silently choosing a supported alternative.
Duplicate copies of the same structural program execute once.

The existing guarded provider retains its finite generation/repair policy and
transport journal. The entry records original invocation evidence, materialized
response, all preparation outcomes, selection, native results, model/backend
call counts and stage timings. An injected provider exception without a ledger
has an unknown model-call count, rather than a fabricated zero. Failed stages,
empty answers, unavailable capabilities and budget exhaustion remain distinct.

The default question budget permits three candidates, 20 retrieval results,
four prompt candidates per slot, 10,000 result rows, 4 MiB of bindings, four
backend calls and a 900-second stage deadline. Deadline checks occur between
stages; provider/client timeouts bound individual calls. This is not in-flight
cancellation. Exact answer scope is the declared partial snapshot. Successful
execution does not independently verify NL interpretation correctness or global
data completeness.

`execute_candidate` retains baseline verification as its historical default.
The question entry defaults to serving without a baseline. Optional verification
has separate status, latency and call accounting; a failure or mismatch retains
the already obtained native answer. JSON positional bindings are normalized
into immutable tuples and duplicate/conflicting positions are rejected. This
fixes list-versus-tuple matching and prevents subsequent caller mutation.

## How to run

The offline example is `python examples/freebase_question_demo.py`. The real
development entry is:

```sh
python -m xgap.experiments.freebase_question_cli \
  --request request.json --catalog catalog \
  --model-bundle models/qwen3_32b_vllm_cwru_grailqa_inline_v1 \
  --tokenizer-snapshot /path/to/pinned/tokenizer \
  --tokenizer-revision 9216db5781bf21249d130ec9da846c4624c16137 \
  --context-limit 12288 \
  --neo4j-descriptor neo4j.yaml --fuseki-descriptor fuseki.yaml \
  --output /path/to/new-run --execute
```

The request contains `question` (`question_id`, `text`), `mapping` (mapping ID,
snapshot SHA-256 and explicitly declared scalar properties), `requirements`
(anchor policy, answer position and optional confirmed positional bindings),
and optional `budgets`. Use only inference-owned entities and data. Descriptors
point at already loaded services; credentials stay in their existing environment
variables. The output directory must be new. `--verify-baseline` adds the
full-Fuseki comparison. CLI results and the provider journal retain failures;
credentials are redacted. Serving-tokenizer parity is explicitly unverified.
This CLI does not claim the frozen CWRU whole-run admission gate.

## Actual observations

Both locked native products, Neo4j 5.26.30 and Fuseki 5.6.0, ran locally on Java
21 against the retained D202 first shard. The model endpoint was a controlled
local HTTP response fixture with synthetic token counts, **not a live LLM**.
The actual guarded provider, HTTP transport, inline materializer, candidate
compiler and native execution ran together. The controlled recording/track/
release fixture is the source-checked D203 case, not a benchmark sample.

| Mode | Native answer | Backend calls | Verification |
| --- | --- | ---: | --- |
| Resource path, serving | One release `g.11b6c7l7m9` | 1 | Not requested |
| Same path, explicit verification | Same release | 2 | Full Fuseki matches |
| Path with string track number `"1"`, serving | Same release | 3 | Not requested |

The scalar mode includes reached-data encoding validation before filtering.
These call counts show that normal serving omits the optional baseline; they
are not measured speedups. Actual question text/catalog retrieval is covered by
offline integration; native acceptance starts at the exact controlled request
and prompt view. Fresh catalog-to-Qwen-to-native accuracy remains unmeasured.

The first native diagnostic passed both resource modes, then its temporary
fixture incorrectly emitted `property_eq` instead of `property_equals`. The
inline validator rejected it before backend dispatch; the fixture server had
no repair response and disconnected. This failed trace is retained. A separate
scalar-only diagnostic corrected just that fixture after offline validation;
no production change or rerun of passed resource modes occurred. Both diagnostics
stopped their owned services normally (Neo4j exit 0, Fuseki SIGTERM/143); no
SIGKILL or source reload. No service remains from this milestone.

Raw roots are `/Users/anthonyche/xgap-data/d205-native-question-20260910` and
`/Users/anthonyche/xgap-data/d205-native-scalar-20260910`. The
[durable receipt](../../experiments/artifacts/d205_native_question_execution_20260910.json)
retains both diagnostics, the fixture correction, provider journals, source
hashes and software validation. It explicitly marks `live_llm=false` and
`paper_result=false`.

## Validation and next gate

Focused provider/question/execution regression: **178 passed in 2.29s**.
Full offline suite: **2,849 passed / 38 skipped in 627.60s**, original session
99584 exited 0. This adds 22 passing test cases to D203. Harness and 22 examples
pass, 23/23 entrypoints. Tests cover actual guarded-provider materialization,
repair/failure accounting, ambiguity, backend budgets, deadline observations,
empty answers, optional verification failures/mismatches, immutable goal
bindings and the explicit CLI with output/credential handling. An earlier CLI
test failed because its descriptor monkeypatch replaced the compiler's default
profile; narrowing the test fixture fixed it without changing production code.

The next gate is actual model-generated anchored answers on inference-owned
execution facts, followed by equivalent-meaning physical-plan comparisons.
The queued CWRU job **3799513** remains a separate frozen 18-question
semantic-only comparison. During the 2026-09-10 07:32–07:38 UTC review it is
PENDING, no start time;
last scheduler reason is Resources. The user authorizes compatible alternate
GPUs when H100 is unavailable. H100 remains first choice; observed DGX node
dgxt001 has all 8 GPUs allocated, and no compatible free alternate has yet been
confirmed. No duplicate job or configuration change was made. Any actual
fallback must record the hardware/serving profile and retain model/precision;
it cannot masquerade as the original H100 deployment contract.

Date ordering, general multivalued/variable-length semantics, broad dataset
coverage, evidence passage/vector retrieval, candidate ranking and comparative
performance remain outside this completed slice.
