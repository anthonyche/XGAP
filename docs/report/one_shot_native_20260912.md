# One-shot native integration — first guided answer and retained failures

2026-09-12. Four small, separately configured integration attempts are retained;
they are not an evaluation campaign or a four-question accuracy sample. Each
attempt made one external request, with no automatic retry. Raw outputs remain
under `/Users/anthonyche/xgap-data/one-shot-native-20260912-<checkpoint>/`.

| Checkpoint | Explicit wire/local configuration | Actual outcome |
|---|---|---|
| b008775 | Original outer schema, original admission/prompt | Misnested parameters; binding rejected before planning. Four independent training queries completed and the model was frozen. |
| bc4103c | Typed wire schema and typed local admission | HTTP 500; token use unknown. No interpretation or final query. |
| f6cb7d5 | JSON object, full typed schema in prompt, typed admission | Response `{}` rejected; no final query. |
| 41a3cca | Original envelope wire, corrected nesting prompt, typed admission | One selected bind plan, two Fuseki queries, exact independent answer. |

The last three attempts reused the same frozen model with zero new training/fit.

## Latest accepted milestone

The fourth explicitly configured attempt, 41a3cca with envelope-schema-v1,
completed the first guided real B01 precision answer. One model request used
2,150 input and 847 output tokens. One interpretation was admitted; three source
placements yielded six admitted physical plans (construction bound nine). They
were scored using the frozen estimator, with no current-query execution observations.
Only the selected left-to-right entity-bind plan ran: two Fuseki queries returned
one row, exactly matching the independent gold after the result was sealed.

The answer is person `https://xgap.test/toy/c`, edge `https://xgap.test/toy/e4`.
Core online time was 4,583.866 ms: interpretation 4,454.744 ms, catalog loading
0.387 ms, grounding 0.733 ms, planning 48.665 ms and final execution wrapper
79.173 ms. The scheduler itself took 78.932 ms. These are a single development
observation, not averages or speedups. Both chosen source assignments were Fuseki;
Neo4j was available and loaded but did not receive a final query in this attempt.

There was zero current-query probing, zero new training and zero fitting. The
earlier frozen model was reused unchanged. Current service setup (6,948.644 ms),
fixture loading (262.314 ms) and model reload (0.525 ms) are separate from the
online core. Whole owned lifecycle 23,518.708 ms includes cleanup. All 432 input
fingerprints match; owned PIDs 5516/5551 stopped without SIGKILL, and a subsequent
process check found neither present. [Accepted checkpoint and hashes](../../experiments/artifacts/one_shot_native_envelope_20260912.json).

The selected runtime prediction was only 0.005412 ms, severely below the observed
78.932 ms. Twelve features are outside the four Match-only training examples'
range, including bind/join/path/project shapes. Larger filtered training plans
happened to have shorter labels; log-ridge learned negative node/dependency
coefficients, which made a larger DAG's extrapolated cost unrealistically small.
Moreover, swapping Path and Match between the two backends can yield identical
current feature vectors. More samples alone cannot fix that representation gap.
This verifies that selection uses the estimator; it does not verify useful cost
prediction, ranking or an efficiency advantage.

Next: represent operator/backend/workload associations, add independent tiny
training coverage and explicit extrapolation handling; verify a necessary
Neo4j–Fuseki cross-store slice; and add an NL-only/performance input boundary.
Do not fit this B01 observation into its own future estimator or rerun accepted
tests. The 64 new targeted risk cases across this implementation are engineering
tests, not 64 benchmark questions. No new baseline/ablation/scale campaign ran.

## Input scope and historical attempts

Input scope: these tiny gates use the ordinary request entry with B01's original
NL text, frozen runtime context, declared output fields and prepared hard request
constraints (including operator IDs). No gold rows, full gold program or native
query is supplied to inference. This checks the configured boundary; it does not
yet verify an unaided NL-only request with no prepared constraint declarations.
That input profile remains an explicit core-acceptance item before evaluation.

## First attempt: parameter-format failure

The external qwen3.8-27b served alias handled **one request**, with2,077 input and
920 output tokens. Precision permitted up to3 candidates; the response supplied
one candidate. The then-current outer structural admission accepted it, but typed
binding rejected its misplaced entity reference. Planning and final query
execution never started:0 current-question backend calls,0 PROFILE,0 final plans.
This is no answer due to an Interpretation format error, not a wrong result from
a successfully executed query. The original result remains
`no_executable_interpretation`; later validation must not rewrite that history.

All four catalog lookups succeeded (Alice, knows, people,30). The failure is not
catalog construction or missing candidate coverage. The generated Traverse put
`constraints` and `required_capabilities` inside `parameters` as well as at the
operator level. It also nested target/selector/restrictor/condition/max_depth
inside the regex `expr`, rather than at the path-pattern level. The old generic
parameters wire schema could not exclude these shapes. Binding correctly refused
to turn the decorative entity occurrence into an enforced identity constraint.

Next fix: share a finite typed parameter contract between v2 wire schema and
admission, reject both illegal shapes before grounding, and replay the original
failed response locally. Do not delete/move fields to manufacture a successful
old answer or repeat its external request. A subsequent new protocol diagnostic
must be separately recorded. Ordinary controlled slices remain accepted.

## Completed separate infrastructure / training work

Both real tiny stores started and loaded successfully. Four independently declared
Match training plans completed, one call each:Neo4j two, Fuseki two. Their measured
scheduler labels were166.844,49.875,53.696 and10.787ms. IDs excludeB01–B05 and did
not use gold. The measured ridge model was frozen and reloaded with the exact
source snapshot and training evidence. Reuse it; do not collect these four again.
This demonstrates the offline fitting pipeline, not calibrated join/bind costs,
selectivity estimation or predictive generalization.

Input preparation18.509ms, service setup8,406.498ms, fixture load273.460ms,
training collection286.570ms and outer fit1.254ms are separate from B01's online
core5,766.314ms. The wrapper including extra preflight, persistence, independent
post-seal evaluation and receipt took5,776.258ms; its9.945ms residual is not solely
write time. Whole owned lifecycle26,316.888ms includes shutdown and is not query
latency. Unknown/new versus historical costs must remain distinguishable on reuse.

An independent read-only audit checked the four measured-file hashes, model and
collection linkage, five online files and evaluation's sealed-result hash. All430
input fingerprints match before/after. Owned Neo4j PID1150 and Fuseki PID1193
stopped without SIGKILL; independent process queries found neither present.
No new model, native execution, old test gate or large-data run was repeated.

The user-approved Sep14 17:00 core and Sep18 real-evaluation targets remain.
New-profile real NL-to-final-answer verification is still open. Existing FinBench
results, LINK3/5, original populations and remote3804210 remain unchanged.

## New protocol fix and reuse readiness

The v2 candidate interface now shares `xgap-semantic-parameters-v1` between its
wire schema and local admission. The development profile advances to v2 with
explicit nesting guidance. Historical single-program parsing and the identity
enforcement rule remain unchanged. This is a bounded structural contract for the
nine existing operators, not additional query semantics or a semantic-correctness
proof.

Five new targeted checks passed on their first run (0.19 seconds): exact saved
failure replay, an independent path-nesting error, the prior correct tiny
candidate, nine operator parameter shapes, and the complete precision request
byte guard. The saved failure now has `no_admissible_interpretation` under the new
contract, with zero external calls; its historical outcome above stays intact.
The complete B01 precision wire is 33,337 bytes against the 65,536-byte ceiling,
with a 6,144 output-token reservation. Exact input tokenization and context fit
remain unverified. The schema and prompt hashes are respectively
`b8647be9dffe1aa6bbf06318a209b19c0e0b6aa539d5e9e1cc00bec87fd0d2ee` and
`560dc1ad5337dade405c730576ca3d6aec64707bd6fa65cbdd0201fd0ea8c0e0`.

The native harness's `--estimator` path passed one new zero-call preflight at
`/Users/anthonyche/xgap-data/one-shot-estimator-reuse-preflight-20260912-v1/`.
It checks the exact source statistics, model integrity and training exclusion;
skips training-plan construction, collection and fit; and separates historical
cost provenance from current reload/loading costs. An independent read-only
review found no blocking defect. No previously accepted gate was rerun.

## New typed-protocol attempt: HTTP 500 before interpretation

The separately recorded bc4103c attempt reused the frozen estimator successfully:
zero new training queries, zero fits, and the original model hash unchanged.
Both tiny stores loaded, but the one external request returned HTTP 500 with an
empty `InternalServerError` message. No interpretation, planning or final query
execution followed. This is one request attempt, not a completed model generation;
input/output token counts are unknown, not zero. Core failure latency was
152.452 ms, not successful-query latency. Current service setup (7,421.087 ms),
fixture loading (261.073 ms) and model reload (0.599 ms) are separate costs.

The 432 input fingerprints match; owned Neo4j PID 3795 and Fuseki PID 3845 stopped
without SIGKILL. Original artifacts are retained at
`/Users/anthonyche/xgap-data/one-shot-native-20260912-bc4103c/` and summarized in
[the second attempt checkpoint](../../experiments/artifacts/one_shot_native_typed_20260912.json).

HTTP 500 alone does not establish that the service rejects recursive structured
schemas. The next bounded engineering step is an explicitly chosen compatible
wire profile with identical local typed admission; it must have a separate
request identity, no automatic fallback/retry and no weakening of hard binding.
The old failed request is not replayed against the provider. Real NL-to-answer
acceptance remains open.

## Explicit compatibility profile prepared

`json-object-v1` is now an explicit pre-dispatch choice. It places the identical
typed schema in fixed prompt text and asks the service for one JSON object;
local typed admission, hard-constraint checks and one-call behavior are unchanged.
`json-schema-v1` remains the default, with its previous prompt identity intact.
There is no automatic profile switch after a failure.

Three new controlled checks passed once (0.29 seconds, tool chunk 1d2863): wire
identity and complete request budget; independent admission of good/bad siblings
including fabricated entity authority; and HTTP failure with one call and unknown
token use. The precision wire is 35,239 bytes, with the same typed-schema hash and
new prompt hash `33045f3fa519c04397fe879c92dd0775c6e52fd756c79871823ac9dd6e6f973d`.
The prepared native CLI accepts this explicit profile and the reused estimator.
This checkpoint alone does not establish real endpoint compatibility or success.

## JSON-object attempt: response received, empty object rejected

At f6cb7d5 the service returned a response to the explicit JSON-object request:
7,380 input tokens, 3 output tokens and payload `{}`. The unchanged admission
rejected the missing envelope as `interpretation_invalid`. There were no admitted
candidates, planning calls or final queries. The successful HTTP response does
not imply a usable interpretation. Core failure latency was 658.695 ms.

The existing model was again reused with zero new training or fit. All 432 input
fingerprints and the model hash match. Owned PIDs 4722 and 4754 stopped without
SIGKILL; an independent process check found neither present. The original result
and [third checkpoint](../../experiments/artifacts/one_shot_native_json_object_20260912.json)
remain immutable; no automatic request retry occurred.

The next explicit profile retains the original bounded envelope schema that
previously elicited candidates, the new precise nesting prompt, and the stricter
local typed admission. Wire enforcement and local admission will have distinct
hashes. This is an interface integration step, not an accuracy comparison among
prompts, and no parameter checker or hard constraint will be weakened.

That envelope profile is now implemented. Three new targeted checks passed once
(0.25 seconds, tool chunk f73650). The precision request is 12,734 bytes; wire
schema hash exactly matches b008775
(`31415283e165b204a1b3cec38f069e9ea4773585a3ebb6a30f553bd282d1099f`),
while the local typed schema and nesting prompt retain their bc4103c hashes.
The candidate-specific config records both hashes and `schema_profile=envelope-v1`;
the previous two profiles and default are unchanged. Real acceptance is pending.
