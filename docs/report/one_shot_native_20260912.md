# First new-profile native attempt — retained Interpretation failure

2026-09-12; code checkpointb008775. This was one small integration attempt, not
an evaluation campaign. Original raw outputs remain unchanged at
`/Users/anthonyche/xgap-data/one-shot-native-20260912-b008775/`.
[Machine-readable checkpoint](../../experiments/artifacts/one_shot_native_20260912.json).

## Actual outcome

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

Next is one separately recorded request using this new protocol and the existing
frozen estimator. That request is not yet evidence of a successful final answer.
