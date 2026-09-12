# Compact financial intent lowering — 2026-09-12

The compact query schema and deterministic compiler are implemented. Three
independently authored financial intents now lower to existing semantic operators
and execute to their independent expected answers on separate saved graph/control
RDF facts. This closes the intermediate-column/property-read/join-construction
implementation gap. The compact provider and ordinary recorded NL entry are not
wired yet, so this is not a new LLM success or full-system completion claim.

## Evidence and meaning

Input is the accepted8-entity/16-relationship tiny snapshot at
`/Users/anthonyche/xgap-data/financial-binding-native-20260912-v1/rdf`, verified through
the existing pinned input loader. It was not regenerated or reloaded into services.
New intents and hand-derived answers live in `tests/test_compact_lowering.py` and
do not call `financial_program` or feed gold plans into runtime interpretation.

| Meaning | Independent result | Lowered operators | Required graph/control reads |
|---|---|---:|---:|
| Alice-owned account transfers to blocked company accounts, closed Jan1–Jan4 window, grouped sum | account2:66; account3:9 |19|5 /3|
| Account1 temporal reachability,1–3 hops, strictly increasing time and no repeated nodes, qualifying media | Four endpoint/distance/medium tuples, including account3 at distance2 |32|9 /3|
| Incoming transfers to company accounts qualified by high-risk media, Jan4 excluded, qualifying account counted once | company1:56 |16|4 /2|

The compiler generates SPARQL with the existing source compiler, executes it in
RDFLib against the corresponding graph or control facts and uses the existing
federated scheduler/coordinator operators. It does not fabricate backend rows.
Reads shared across providers use conservative union. These counts describe the
compiled local correctness plan, not measured native latency or a new planner
comparison. Test execution uses one declared compiled plan per changed intent.

Further distinct checks establish:

- Adding a separate10.125 transfer with otherwise identical values changes the
  risk aggregate from56 to66.125; two qualifying media do not double it.
- Two repeated transfer patterns sharing both endpoint variables yield14 edge
  pairs; joining only on the first endpoint would incorrectly produce24.
- Excluding Jan1 removes the two-hop result; equal/decreasing timestamps do not
  become valid increasing paths.
- A same-variable closed temporal cycle yields no ACYCLIC row and one length3
  WALK row. This also checks repeated endpoint aliases and reachability dedup.
- Missing property coverage, partial edge-attribute coverage, raw technical-ID
  literals and invalid post-dedup references fail before execution.
- Boolean/floating hop bounds and the unexposed SIMPLE mode are rejected.

The first targeted run passed7 cases in1.11s. Contract review identified that
the audited SIMPLE permits a closing endpoint repeat, whereas this financial
meaning prohibits all repeated nodes. The compact name is now ACYCLIC, preserving
the original algebra. Integer-bound validation was tightened at the same time.
The two affected path cases plus two new boundary cases passed in1.04s. Thus nine
distinct cases are accepted, with two justified repeats after the actual change;
no old accepted suite was rerun. Commands used the existing directed-test Python
environment and `PYTHONPATH=src:tests`, targeting `tests/test_compact_lowering.py`.

No new model requests, native-service queries, baseline runs, training/fit,
current-question probes or large-dataset executions occurred. Local RDF query
execution is test evidence only. Existing financial NL v1/v2/v3 failures and costs
remain unchanged; they are not repaired by these deterministic fixtures.

## Next bounded step

Add an explicit compact provider profile and wire it into the existing frozen
profile/record interface. Retain raw compact candidates and deterministic lowering
provenance, admit invalid candidates independently, charge lowering online, and
preserve one model call, bounded top-K, frozen estimation and one final plan.
Check the new compiled workload's compatibility with existing fixed budgets/model;
do not assume old six-candidate coverage proves it or retrain preemptively. Then
run one necessary tiny real financial NL boundary. Both native baseline methods
are already runnable and stay untouched; their wrong answers/failures remain
measured outcomes. Core Sep14 17:00 and real-results Sep18 targets remain active.
