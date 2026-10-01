# External LLM connected; first real federated answer exposes projection mismatch

2026-09-11, parent c0e32434e05317c15cb6062ee1aa06c9af3e57f6 plus the separately
fingerprinted external wiring. This is LINK development evidence, not a paper
benchmark or a claim that the complete five-question gate passed.

## Observed result

After the administrator reported no whitelist and the user explicitly requested
another connection attempt, the current system/proxy network path returned HTTP
200 from both `/v1/models` and `/v1/chat/completions`. The supplied served alias
`qwen3.8-27b` matches the generation response; the schema probe returned
`{"status":"ok"}`, `finish_reason=stop`, 23 input/7 output tokens in174.70ms.
The service advertises vLLM and a262144 context limit, but its `/model` root and
alias do not identify an independently verified checkpoint/tokenizer. The earlier
20-second no-HTTP-proxy timeout remains a failed observation; routing/firewall
state was not changed by this work and its exact cause is not established.

The unchanged five tiny questions were then sent once each, with B01 followed
by the explicitly selected B02–B05 window. All five passed the existing semantic
parser. Their complete recordings were copied byte-for-byte into one native
replay directory; copying made no model call.

| Question | Input tokens | Output tokens | Interpretation seconds | Native evaluation |
|---|---:|---:|---:|---|
| B01 |1652|848|4.941|Executed; strict answer mismatch|
| B02 |1652|848|5.575|Not attempted after B01 failure|
| B03 |1652|848|4.861|Not attempted after B01 failure|
| B04 |1669|380|2.449|Not attempted after B01 failure|
| B05 |1661|848|4.953|Not attempted after B01 failure|

Toy generation totals:5calls,8286input+3772output=12058tokens,22.779s of
Interpretation. The separate schema probe adds one call/30tokens. These are
reported usage and separate staged timings, not colocated NL-to-answer latency.

The real native replay started fresh Neo4j5.26.30/Fuseki5.6.0 toy stores. For
B01, the ordinary agent resolved catalog holes, used P1 `coordinate_two_passes`,
placed `paths` on Fuseki and `people` on Neo4j, and successfully joined their
actual outputs. It made4planning-observation+2selected-execution calls; replay
made0model calls. Agent execution took402.25ms. Fixture loading and health/startup
are separate costs. The observed result was:

```json
[{"person":"https://xgap.test/toy/c","age":40,"edge":"https://xgap.test/toy/e4"}]
```

The frozen gold requires only `person` and `edge`. The model's final Project
includes an extra `age` field. Therefore the strict gate failed:0correct out of
1evaluated,4unattempted. Entity/edge values agree, but no column was dropped to
turn this into success, no gold was changed and no response was repaired. The
failure is a returned-schema mismatch, not a catalog-build or transport failure.
Native exit1/phaseB01 and both successful service shutdowns are preserved. The
later candidate/reference checks and retained vertical slice were not reached.

## Engineering change and focused evidence

The new `external_toy_interpretation` factory/CLI explicitly binds URL, model and
key-environment name, reusing the existing v2 prompt, schema, provider, parser and
replay. Credentials remain outside configuration and artifacts. It uses an
explicit development byte budget, with no old32B tokenizer or exact-token claim:
64KiB serialized request,4096output reservation,120s socket timeout,1MiB received
response cap, no redirects and no retries. CLI defaults to zero-call preflight.
It permits a contiguous1–5question window, preserving all five IDs and unknown
usage; all five actual requests were10170–10254bytes. Model context-fit and exact
input token counts were not locally verified before dispatch.

The shared runner now persists started/unknown state before provider entry and
the received result/cost before recording export. A recording-write failure
stops the remaining window without erasing the model attempt. Actual recording
size is checked against the replay reader's4MiB bound.

First focused run:18new+1affected legacy check passed in0.69s. A subsequent
review found the interrupted/export-failure ledger gap; after fixing it, only
one added test ran and passed in0.20s. Each run has unchanged before/after source
hashes. The controlled loopback→ordinary P1→tiny RDFLib slice and replay are test
evidence, distinct from the actual external generation and native run above.
No broad suite, large-data development run or remote Slurm action occurred.

All340 source/prompt/model-runner fingerprints still match the actual-generation
snapshot. Original Qwen32B0/5, FinBench6/6, original150/48 populations and exposure
markers remain unchanged. Different model and serving environment prevent
attributing this run's behavior or latency difference to promptv2 alone.

## Remaining work

The external API can replace Pioneer LLM serving;3804210 remains the user's
independent pending frozen job. LINK strict correctness is unfinished. Next use
these saved responses to investigate the output projection contract and local
failure replay before any new model/native attempt. Preserve the five statuses
and extra-column failure; do not silently project evaluation gold columns.
Real-data coverage, calibrated prior costs and fair E1–E5 remain necessary.

Raw evidence: `/Users/anthonyche/xgap-data/external-toy-wiring-20260911/` and
`/Users/anthonyche/xgap-data/external-llm-reconnect-20260911-2321/`.
[Machine evidence](../../experiments/artifacts/external_toy_link_20260911.json)
binds timings, source/recording hashes, test receipts, exact rows and cleanup.
