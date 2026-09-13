# Compact entity-role prompt v2 — 2026-09-13

RQ: can the ordinary one-shot frontend distinguish named references from bound
business-ID predicates and generic graph variables, without extra model calls?
X: explicit prompt contract; Y: emitted holes, grounding outcome, final tiny
answer equality, model/lookup/source calls. This is prototype integration, not
a claim of improved held-out accuracy or a baseline optimization.

Frozen real NL group1 failed for all shared-front-end methods: the model wrote
generic role descriptions as required entity mentions, although a business-ID
predicate was already present. The current compact language/compiler can express
the correct distinction without changes. Required mentions continue to ground
or fail; do not drop them, look up generic type labels as entities, inject IDs,
repair candidates after a failure or use reference answers in inference.

Publish a new prompt file; preserve v1 and all frozen profiles. V2 explicitly
specifies null entity fields for ordinary variables, stored-property predicates
for literal business IDs, and original proper names for entity grounding. It
also restates that a path-length field is not a deduplication identity. Wire
schema, lowerer, grounding, planner, estimator, data and output semantics remain
unchanged. Both modes use the same prompt; existing K/token/policy bounds remain.
The compiler and estimated selection retain their existing polynomial bounds.

Scope: compact provider version choice, a prompt-only frozen-profile derivative,
three independently authored tiny requests/references, focused boundary checks,
and one live pass of each new tiny request using frozen native stores. No baseline
engine, profile tuning, catalog build, estimator fit or large-data development.
Named mention, business-ID and generic-variable cases each get at most one model
call and one final plan. All outcomes, including failure, are retained. This
does not repeat the old formal questions or change their scores.

Any later evaluation must preserve population and method order and disclose the
new prompt and prior exposure. Shared-NL external methods receive the same new
frontend version; their pinned native implementations remain original. A prompt
revision cannot be silently substituted into an old immutable campaign profile.
Do not call a development success an overall effectiveness result.
