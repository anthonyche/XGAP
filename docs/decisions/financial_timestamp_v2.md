# Local-calendar millisecond lexical compatibility v2 — 2026-09-13

RQ: does the bounded deterministic meaning preserve valid source time values and
therefore answer correctness? X: omitted fractional zeros in a local calendar
timestamp. Y: filter/path/aggregation equality against independent tiny answers.

Native fixed group 10 returned ten rows but EM=0, row-multiset F1=0.8. Saved
source records contain 79,909 transfers: 71,892 with three fractional digits,
7,202 with two, 718 with one, and 97 with none. The v1 Filter required exactly
three digits; it rejected 8,017 source times, including ten eligible transfers
in this question's window. Adding those saved contributions accounts exactly
for the frozen top-ten reference. This is a core data-contract defect, independent
of identity-map projection, model interpretation or estimator ranking.

The v2 timestamp_ms domain is valid Gregorian local-calendar strings in years
0001–9999, with fixed date/time fields, hours 00–23 and seconds 00–59, and either
no fraction or one to three fractional digits. Missing fractional digits are
zeros: .14 = .140; no fraction = .000. Comparisons use the canonical padded
value, including equality and strict increasing-time comparisons. No timezone,
date-only, arbitrary ISO text, leap-second, 24:00 or submillisecond coercion is
admitted. Invalid/null remains false, including inequality; NOT complements it.
Scalar comparisons and the path algebra remain unchanged. Finite input length
and a fixed calendar check keep each time comparison O(1); planner bounds and
the candidate domain remain unchanged.

Allowed changes: shared lexical contract, coordinator timestamp filter and our
shared-NL global SPARQL compiler's equivalent predicate, a saved failure extract,
focused tests and an affected tiny slice. Both compiler paths implement the same
meaning. This fixes our common input bridge, not FedUP/FedX algorithms or semantic
capabilities. Fixed baseline query artifacts remain unchanged. No prompt/schema,
source/catalog/model/reference rewrite, budget increase, fit, probe or retry.

Acceptance: independently expected lexical equivalence and invalid boundaries,
strict time ordering, tiny parallel-transfer aggregation, global SPARQL parity,
and one estimated tiny slice. Saved full-output analysis is diagnosis only; it
must not replace the original returned answer or score. Historical groups and
versions stay separate. Future evaluation needs an explicit implementation epoch;
the exposed group is not rerun as development or presented as fresh effectiveness.
