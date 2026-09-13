# Next bounded gate: frozen equality-key multiplicity

2026-09-13, next engineering design after the accepted source-bind component.
Implemented in630d802/e9acb6b; see [the accepted contract](equality_key_bounds_v1.md) and
[real tiny/full-source/NL evidence](../report/equality_key_bounds_20260913.md). The historical design below is retained.

The saved full group6 property responses each contain20409 account rows, but
the original scalar equality produces one distinct canonical anchor key across
the graph/control union. The frozen work estimator uses30000 path-bind record
units across three requests (the10000 binding cap per target). Its largest
fanout-minus-coordinator term is11468.808 estimated ms. The feature is a coarse
work proxy, not a calibrated cardinality prediction. New source binding alone
therefore leaves ordinary estimated selection on coordinator. Do not force
fanout, rerun this question, or fit to these exposed outcomes.

Next implement only tiny offline statistics and bound propagation needed for
this prototype, then publish explicit frozen artifacts before real evaluation:

1. Compute, from complete independently supplied source node facts, a maximum
   number of distinct entity keys sharing any exact string value, per logical
   source snapshot, node label and property. A conservative matching-row maximum
   is also safe if duplicate records inflate it. Start with exact strings to
   cover business IDs; unsupported scalar types remain without a tighter bound.
   Freeze input hashes, complete-coverage scope and preparation cost. Do not use
   query answers, selected evaluation literals, or a runtime source query.
2. Carry the optional facts through the existing logical source/profile inputs.
   Missing or mismatched snapshot/type coverage must not become an invented
   small cardinality. Preserve old profiles and their predictions; publish a
   new source-statistics/profile version, not a silent update.
3. For the already proved anchor union, sum the applicable source bounds. Use
   this bound to tighten the actual binding-list resource bound (at least1 for
   the existing positive-limit contract), capped by the user's existing limit.
   This fits the existing feature basis: actual execution and prediction then
   see the same smaller max_bindings. Keep weights/features unchanged and the
   original dynamic key extraction/overflow checks. If any leaf lacks a bound,
   retain the original limit. Do not assume uniqueness from the field name id.
4. Tiny checks: duplicate values, provider unions, empty/missing properties,
   unsupported scalar types, wrong snapshot/hash, no metadata and a real frozen
   estimator. Verify exactness and bounded domain, then one estimated-choice
   native slice on independently authored tiny facts. No new full request until
   this integration is coherent. If insufficient, inspect evidence and revise;
   do not alter numeric coefficients merely to make a desired plan win.

This is offline information acquisition plus static resource-bound refinement,
not online probing. The equality-multiplicity preparation is one-time and
query-independent; the final key reads still belong to the single execution
plan. Update the explicit polynomial bound for any extra lookup/propagation.
Do not add a general histogram product, fresh benchmark, broad ablation or
unrelated source optimizer for this gate. Actual ranking gains remain unknown.
