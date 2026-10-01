# Typed binding values for coordinator operations

2026-09-11, design frozen before implementation; accepted after native gates,
3334 passed/38 skipped and all24 harness/example entrypoints. See
[acceptance report](../report/toy_backbone_t1_typed_bindings.md).

Goal: close observed scalar precision, RDF numeric, grouping, nullable ordering
and count(field) gaps through the normal semantic DAG, planner and runtime.
This is binding-row semantics, not a change to PathSet Selection, M6 bindings or
path GroupBy/OrderBy. Path atomic equality retains its audited bool=0/1 rule;
the existing binding Filter already distinguishes booleans from numbers.

Scope: shared runtime scalar/value helpers; binding row Filter/Project/Union,
Join/SemiJoin, Aggregate/OrderLimit; semantic compile validation/metadata; tiny
independent fixtures, tests, harness and reports. No new algebra/runtime
operator, model, catalog build or large benchmark. Historical artifacts stay
frozen; compiler metadata identifies the new binding value profile.

Values and equality:
- JSON integers, finite floats, booleans, strings, None and explicit RDF terms
  remain distinguishable. RDF integer/decimal/float/double values are numeric;
  plain numeric strings are strings. Invalid/nonfinite numeric terms fail.
- Binding numeric comparisons use decimal value representations (as existing
  Filter does for JSON floats), retaining exact integer/decimal comparison.
  Integer1, float1.0 and RDF decimal1.00 share a numeric value key; True does not.
- Filter equality, join keys, group keys and duplicate elimination share those
  keys. Unknown RDF kinds/datatypes retain full term identity. Structured row
  payloads retain recursively typed identity; they are not silently stringified
  into scalar arithmetic. No implicit URI/string identity conversion.
- None is an explicit unbound scalar; an absent required row field is still a
  schema error. Atomic ordinary comparisons with None are false; NOT complements
  them, consistent with current binding Filter. Nulls share a group but do not
  join as bound keys. Output representations and tie-breaking are deterministic.

Aggregation:
- COUNT(*) counts rows; COUNT(field) counts non-null values. DISTINCT is an
  optional boolean on each aggregate, using binding value equality. COUNT(*)
  DISTINCT counts distinct complete rows.
- SUM ignores nulls, rejects nonnumeric non-null values, and keeps integers as
  integers. Decimal+integer sums stay exact and return an explicitly typed RDF
  decimal; this avoids losing precision in JSON. Any floating input promotes
  the sum to a finite float after the existing decimal-value accumulation and
  one final conversion (ordinary floating output precision, no exactness claim
  for mixed large integer/float sums). Empty SUM is integer0.
- MIN/MAX ignore nulls and use the same scalar order as OrderLimit. Empty/all-null
  MIN/MAX return None. Empty global aggregate still emits one row; empty grouped
  input emits none. No input field means COUNT(*) only.
- Representatives of equal numeric group keys are selected deterministically,
  preferring integer then decimal then float without changing original rows.

Ordering:
- Numeric values compare numerically, strings lexically, booleans false<true.
  Mixed scalar families have an explicit order: number, string, boolean, RDF
  term (term identity). Containers are not orderable scalar values.
- NULLS LAST is the default independent of ascending/descending; each order key
  can explicitly choose nulls=first or last. Direction reverses non-null value
  order. Complete typed row serialization breaks remaining ties deterministically.

Acceptance: independent module examples for exact large integers, exact RDF
decimals, promotion, bool/string distinction, malformed/nonfinite data, nulls,
count(field)/distinct, group/filter/join consistency and deterministic order;
independent NL→semantic DAG/path sub-IR→expected logical/native plan→typed answer
chains on a tiny graph; normal candidate observation/selection/serving and real
Neo4j/Fuseki cases, with the retained original vertical slice; final shared-core
regression and examples after the implementation stabilizes. RDF-only decimals
need explicit source placement rather than pretending Neo4j stores arbitrary
precision decimals as numeric properties. These gates do not complete T1/T2/T3.
