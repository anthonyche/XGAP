# Anchor-aware relationship budgets — optional scope v1

2026-09-14. Follow-up to [bounded retrieval](budgeted_relations_v1.md). RQ: can
budgeting already bound relationships avoid discarding the request's relevant
keys before they reach the coordinator? X: global-prefix versus anchor-aware
budget scope. Y: source rows/bytes, independent nonempty answer recall, actual
selected strategy and online cost. No new plan family or observations.

`retrieval_scope=bind_after_anchor_v1` requires an explicit performance row
budget. If the existing audited scalar-anchor normalization produced an
`anchor_reduction` in a candidate, cap only its REMOTE_BIND_QUERY relationship
fragments. Keep its unbound relationship reads complete. Thus a coordinator
candidate cannot appear cheap simply by discarding the anchor before its
mandatory filter; a legal bound candidate can apply existing keys before LIMIT.
If no proven anchor normalization exists, retain the original all-relations
budget behavior. Do not infer new anchors, force a physical strategy, add calls
or combine candidate rewrites. Frozen estimated cost still selects the final
candidate. It may select a complete coordinator if that is predicted cheaper.

List uncapped relationship nodes and mark that R(B+1)/RB bounds apply only to
bounded fragments. Full entity reads and unbound relationships are excluded.
This scope deliberately gives up a global relationship-row bound to preserve
available contextual filtering. It cannot guarantee recall: even relevant
bound relationships may exceed B, and all previous aggregate/ranking caveats
remain. Cap membership follows unspecified backend order.

The change adds O(V) inspection to the existing bounded-plan transform and no
new candidate combinations. All Ptime construction/selection bounds remain.
There is no native scan, global latency, execution-memory or unconditional
answer-quality guarantee.

An audit also found that the first budget change updated the outer candidate's
equivalence key but left the old complete-query key in runtime-plan metadata.
That stale metadata claim is now removed: both fields carry the same unique
budgeted-plan identity and explicit plan-only scope. This changes new plan
identities, not previously executed answers. Old artifacts retain their source
commits and are not silently reinterpreted or replayed against a changed plan.

Four new checks pass. On the existing small graph with a late anchor e, the
global prefix produces no answer; binding first retains all five independently
derived answers, with source rows54→33. The ordinary entry selects
anchor_fanout_bind by the frozen analytic estimates, executes once (8 source
calls), and returns those five rows without probing. For anchor a/B2, source
rows54→39 and three of six full-reference answers remain. The initial test's
assumption that this prefix must preserve all six was wrong; full gold was kept
and the proper witnessed-subset/recall scope is tested. An unrelated fixture
namespace typo was corrected. These are mechanics, not calibrated speed/quality
results; no outcomes were fitted or used to tune source/model weights.

`derive_refined_modes_profile` publishes explicit precision controls and this
performance scope while preserving pinned facts, prompt, catalog and estimator
dependencies. One new offline publication/preflight case passes; no external
calls. The child is for XGAP mode development, not an implicit shared-baseline
frontend update. Formal campaign routing must keep baseline frontend settings
from the pinned parent before a new evaluation epoch is released.

Next gate: exactly two real NL requests, one per mode, on the frozen8-entity/
16-relation native graph. New account2 query has two independent full answers.
Freeze B2 and precision deficit0.1 for this wiring gate; they are not final paper
hyperparameters. No old evaluation question, data load, fit or baseline run.
