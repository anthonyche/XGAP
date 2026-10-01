# LINK: actual Qwen responses, preserved failures and stricter admission

2026-09-11; input producer bc2bb67774910225a2e3842da26cb87fa676bf54,
original replay backbone 9f00414f409dedb01415d6f87cb77ea7dbc2fa60.
This five-question development gate is not a held-out benchmark result.

## Outcome

The GPU/model transport works:all five requests completed, with reported usage
and finish_reason=stop. All five passed the old outer-structure/hard-constraint
check. However, replaying those exact responses through the ordinary question
entry completed **0/5** queries. All failures occurred before any backend attempt;
no toy native services were started and no model call was repeated. This replaces
the earlier uncertainty about the job's per-question outputs, not the original
job success record.

| ID | Input tokens | Output tokens | Model call seconds | Original ordinary-entry failure |
|---|---:|---:|---:|---|
| B01 |1376|733|66.757|Unknown/unbound source slot|
| B02 |1376|721|64.536|Unknown/unbound source slot|
| B03 |1376|761|68.004|Unknown/unbound source slot|
| B04 |1392|611|54.646|Threshold mention has no bounded catalog candidates|
| B05 |1386|752|67.214|Unknown/unbound source slot|

Total:model calls5, input6906/output3578=10484 tokens, model-call time321.157s.
The14m28s job duration includes other work and is not model inference time or
colocated NL-to-answer latency. Replay time and historical model time remain
separate. B05 reuses the original authored explicit-selection callback; its tool
metric counts one external clarification, but local replay contacted no user or
network service. Original accounting is retained.

## Cause and implemented correction

This is not a GPU shortage or catalog-build failure. Four responses reference
an undeclared source hole. They also project only person/edge and then filter age,
which that input never produced. B04 assigns a logical source to a coordinator
Filter and references an undeclared source_toy; its initial resolver failure is
because the scalar mention includes comparison words instead of the number.
The original prompt already described Match/property extraction/join, and outputs
were611–761 tokens against a4096 bound, so truncation is not supported as the cause.

The wire JSON schema deliberately admits generic operator parameters. Its old
parser checked the outer graph and copied hard-constraint text but did not check
executable slot/source-reference integrity. Binding still rejected invalid meaning,
so this was early-admission weakness, not silent wrong native answers.

The provider-neutral parser now rejects malformed/undeclared executable slot
references, source-kind references in non-source positions, missing/extra source
assignments, and unknown literal logical sources when runtime context supplies
the authoritative source map. Assignments must cover exactly Match/Traverse.
No-runtime-context fixtures keep their provider-neutral contract. The scan is
linear in the explicit JSON/IR size with dictionary membership checks; it does not
resolve entities, prove field lineage or establish semantic/answer accuracy.

The21 focused tests (17new/4affected) pass in0.50s. A separate replay of all five
unaltered original responses under this correction rejects all five as
interpretation_invalid before resolution. Four identify the undeclared source;
B04 identifies the extra Filter assignment. Raw responses and original usage stay
available. This is correct failure classification, **not** five repaired solutions.

## Next diagnostic is prepared, not measured

The original v1 prompt is preserved. A v2 prompt adds generic reference/source,
numeric-mention and field-availability obligations; the tiny provider points to
v2 with a new provider ID and pinned prompt hash. All five request bodies, explicit
hard requirements, context/source versions and questions match the originals.
No per-question gold program, answer or target query was added. No response was
hand-repaired. Field-flow and scalar-mention failures are not fixed by the new
structural validator and remain explicit obligations for generated programs.

The next independent generation must first run the existing pinned-tokenizer
preflight, then at most five model calls with no automatic repair/retry. v2 has no
new model observations yet:it cannot be reported as an accuracy improvement.
The original0/5 development completion result stays in the evidence ledger.

## Evidence and acceptance boundary

Input archive38083bytes, SHA
`eeb1fa9b3f12e44e5aee57b45d6579cc9e316a8cf57604f4ec80a2cc0691c2e9`.
Twelve original files match the generated transfer receipt; ten stable originals
also match the producer inventory. The inventory/status files have their transfer
hashes recorded separately. Original request/response hashes, source/model
versions, current question/runtime identities and usage were independently checked.

Raw input, first ordinary replay, corrected admission replay and prompt preparation
are under `/Users/anthonyche/xgap-data/link-model-3804011-20260911/`.
[Machine evidence](../../experiments/artifacts/qwen_model_link_failure_20260911.json)
contains commands, file hashes and all five outcomes. No broad regression, new
model/native attempt, gold-driven inference or frozen catalog change was performed.

R-E/LINK remains unfinished because valid model meaning has not reached native
execution. The deterministic backbone's earlier accepted toy gates remain valid;
real FinBench integration is a separate test of prepared semantics, not a substitute
for this model-quality gap. A research prototype must report both boundaries.
