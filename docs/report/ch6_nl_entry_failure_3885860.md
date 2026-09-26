# D1 pilot 3885860: shared NL-entry diagnosis and bounded correction

2026-09-26. This records original model responses and offline compiler replay,
not a new method experiment or a forecast of answer accuracy.

The received archive is `xgap-D1-pilot-3885860.tar.gz` (3,107,681 bytes), SHA-256
`1f6eeb1aa7f4d0241f9df53bc682bb45a7dc38351cc32b86fc24ddf77c08c324`.
The deployed source was `c40254728151972252974d63eb4befb311068b3a`.
There are 97 internal-method compressed core records and one external TS cell.

|Original internal entry outcome|Method requests|Underlying observation|
|---|---:|---|
|answered|16|Entry and subsequent execution reached an answer|
|proposal_failed|48|Model compared `c.xgap_id` with `a.xgap_id`; compact compiler required canonical variable identity (`property:null`)|
|proposal_failed|8|Duplicate node/edge variable declarations|
|proposal_failed|4|Relation label `KNOWS` incorrectly declared as a node type|
|intent_outside_proposed_scope|21|Proposals lowered, but queried authority rejected containment|

These are method-request counts, not distinct questions. Repeated responses across
XGAP/NP/SH/GR share an entry implementation and must not be interpreted as four
independent NL failures. The TS source-observer call cap is a separate batch-stop
cause; it does not explain these internal entry failures.

## Exact surface normalization

New runs may explicitly select configuration provider
`frozen_compact_model_equivalence_v1`. The worker adapts the already materialized,
endpoint-bound compact v2 provider and records `provider_adapter`. It preserves
the original profile pin, prompt, wire JSON schema, model settings, token guard,
transport, source snapshot and estimator. Old profiles and responses do not change.

The adapter performs only two bounded exact rules:

1. For two same-type node variables, scalar `eq`/`ne` between their declared
   identity properties becomes `eq`/`ne` between canonical variable identities.
   The source schema must declare a shared identity namespace, and every backend
   must match both that namespace and identity property. Existing canonical
   identity encoding accepts local string IDs and prepends the same namespace,
   an injective mapping preserving equality. Raw literals, business IDs, mixed
   references, different node types, ordering and output values are unchanged.
2. If all output expressions are nonaggregate references, the final result is
   set-valued. An intermediate contribution projection retains all selected
   identities and values and merely removes duplicate witnesses, so it is
   redundant before final set projection. This rule does not apply to aggregates.

The complete original response remains in `raw_compact_response`; the equivalent
copy and per-candidate rewrite ledger are recorded separately. Independent
structural admission and the paid scope-authority call still run. Neither
successful compilation nor this normalization certifies the user's meaning.

Offline replay of all 97 original responses makes **48 of the 60 original
structural rejections lower successfully**. The remaining 12 stay rejected. All
37 originally lowerable responses remain lowerable. No model or backend was
called; this does not establish 48 new correct answers or scope containment.
The replay receipt is outside Git at
`/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/interpretation-equivalence-replay-3885860.json`.

One scope-rejected nonaggregate W1 response uses a redundant contribution list;
the second exact rule addresses that representation. Other scope failures include
COUNT(DISTINCT edge.id) versus contribution-tuple count, business-ID versus
canonical-node comparisons, and an incorrectly changed witness-edge view. These
are not automatically rewritten to match the hidden intent. Invalid declarations
also remain invalid. No gold query or reference answer informs these rules.

## Diagnostics and validation

Ordinary worker receipts now include bounded `interpretation_diagnostics` with
the candidate index and original lowering/admission error. Previously, a lowering
failure produced a null program and the visible receipt only said no candidate
passed admission, hiding the useful original error in compressed provenance.

35 focused checks passed: original-response replay, declined counterexamples,
provider/profile identity, unchanged old compact providers, paid scope rejection,
diagnostic bounds and existing bounded entry behavior. No remote calls or new
server jobs were made by this correction. New small-study execution remains the
test of actual answer quality and end-to-end performance.
