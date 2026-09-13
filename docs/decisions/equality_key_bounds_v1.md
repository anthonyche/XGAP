# Frozen exact-string key bounds

2026-09-13. Implementation of the previously recorded next gate. Scope is the
research prototype's existing necessary scalar anchor, not a general histogram
optimizer. No changes to semantics, interpretation prompts, baseline methods,
estimator coefficients/features, datasets, or the caller's resource policy.

RQ: can independently acquired offline information make estimated work and
executable binding limits consistent? X is presence of a frozen complete-source
string-multiplicity summary; Y is validated binding bound, unchanged answer,
estimated choice, and one ordinary final execution. Tiny checks answer this
engineering question; they do not establish overall speedup or ranking accuracy.

The offline publisher scans a caller-declared complete JSONL source export with
an exact input hash/count. For each covered label/property, count records for
every exact string value and keep the largest count. Duplicate records safely
overcount distinct identity keys. Empty coverage and missing properties give0;
other scalar types do not equal strings under typed_binding_values_v1. RDF
xsd:string and plain JSON strings use the same key. Neither numeric-looking
strings, language-tagged literals nor numeric/boolean values are conflated.

The immutable artifact records source identity, snapshot, namespace, coverage,
input hash/size, maxima, and one-time preparation cost. Profile loading verifies
its exact hash, scope and snapshot/namespace before interpretation. Completeness
and the relationship between source export and frozen snapshot remain explicit
deployment assertions, just like replica equivalence; a checksum alone cannot
prove them. The tiny adapter additionally verifies the exact source load files,
per-batch hashes, eight graph entities and the same eight control identities.
It reads no requests, answers or source endpoint. Its complete string projection
uses the actual control property mappings. It supports only the existing tiny
native snapshot; publishing statistics for full snapshots is still pending.

Each LogicalSource may carry optional FrozenEqualityKeyBounds. A new child
profile pins these artifacts while preserving original source versions,
model weights, feature basis, policy, catalog, prompt and parent artifacts.
Profiles without statistics keep their previous candidate plans/predictions.

For the already-proved anchor driver, visit its Match/UNION leaves. Only exact
string equality is eligible. If every leaf has a bound for its label/property,
sum those bounds; duplicated providers may overcount. Set each fanout target's
actual max_bindings to min(policy_limit,max(1,sum)). The same value is embedded
in the native binding adapter and consumed by the existing frozen work model.
Final key extraction, count/byte enforcement and original answer operators are
unchanged. Missing statistics/coverage retains the old policy limit; invalid
hash/snapshot/namespace fails validation. No new online read, probe, plan retry,
truncation, forced winning strategy or fit is introduced.

Soundness: every surviving anchor key comes from a covered leaf matching the
same string. Its leaf count is no larger than that leaf's maximum matching
record count; DISTINCT keys in their union number at most the sum. The policy
may still be smaller and cause an explicit resource failure, as before. The
positive-limit convention for a proved empty set does not fabricate any keys.

For explicit source export size B and total scalar incidences T, preparation
uses O(B+T) expected hashing work and O(T) worst-case storage; sorting emitted
scopes costs O(S log S) for S entries. This is offline and query independent.
Online lookups use a linear scan of explicit entries, so the added work is
O(D*n*S) for D source placements and n represented semantic nodes. All values
are integer counts bounded by export records; bit costs are polynomial in
their encoded sizes. The existing D*(1+2J+A) candidate bound is unchanged.
Choice minimizes the same frozen estimate on the declared domain. No actual
latency or approximation guarantee is added by a sound key-count upper bound.

New tests: eight cases first passed0.55s; the actual profile case initially
exposed an exporter assumption that explicit backend profiles always exist.
That assumption was removed in favor of the validated client engine. The fixed
profile case and directly affected namespace fixture check pass0.71s. Actual
tiny source maxima sum to2; fanout estimate changes297.949→226.711ms, while
coordinator remains28.933ms and is still the estimated winner. This is not
evidence of a ranking defect on a tiny graph or an observed speedup. A new
zero-bound transport check and ordinary native gate are recorded in the report.
