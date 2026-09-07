# M15-E5 Interpretation–Relaxation Objective Gate

## Status

**OPTION A/R1 FROZEN; E5/E5B/E5C OFFLINE MECHANISMS VERIFIED; NO E5C CWRU RUN AUTHORIZED**

This gate separates unresolved natural-language interpretations from bounded
semantic relaxations before XGAP connects the E4 resolution bridge to
family-memory cost prediction and Pareto/epsilon/K selection. It records a
contract mismatch in the current implementation; it does not select a policy,
change an existing result, or support a paper claim. Every proposed artifact
remains `paper_result=false`.

## Evidence from the implemented contracts

The current layers are individually consistent but are not compositionally
equivalent:

- E4 content-addresses all six meanings produced by the two unresolved holes.
  It preserves their candidate provenance and capability status, but assigns no
  class as the user's authoritative intent and emits no semantic-deviation
  score.
- E2B returns an in-set subset of candidate IDs. Its output is explicitly
  non-authoritative and contains no calibrated confidence or ranking score.
- The F2C9 direct semantic frontier requires exactly one executable class with
  `semantic_deviation == 0`, globally dominates classes on semantic deviation,
  latency, and resource cost, and requires that exact class to be returned
  first.
- The F2C10 family-memory predictor estimates latency and transferred bytes for
  physical plans with zero current-query profiling. It does not estimate user
  intent, interpretation probability, or semantic deviation.

Consequently, an adapter cannot safely feed E4 classes into F2C9 by assigning
zero deviation to the first candidate, the model-returned candidate, or an
ontology-nearest candidate. Any of those choices would create authority or a
calibrated semantic preference that the upstream evidence does not contain.

## The distinction to preserve

An **interpretation** is one possible meaning of an unresolved phrase. Before
clarification or another authoritative binding, two interpretations may both
be plausible; neither is necessarily a relaxation of the other.

A **relaxation** starts from a bound reference meaning and changes only a
declared relaxable slot. It therefore has a defensible direction and distance,
while all hard constraints remain immutable.

The current request illustrates both:

- `single qualifying transfer`, `window-total exposure`, and
  `window-frequency` are alternative meanings of `密切`; no implemented tool
  proves which is the user's reference meaning.
- `transferred_to` versus ontology-adjacent `paid_to` has provenance that could
  later define a bounded relaxation edge, but E2B's non-authoritative selection
  alone does not establish the reference predicate.

## Policy alternatives

### Option A — two-level interpretation sets and relaxation frontiers

Preserve unresolved interpretations as co-equal groups. For each group, retain
only its cheapest predicted physical representative. Apply semantic-deviation
Pareto/epsilon pruning only to declared relaxations that have an authoritative
base inside that group. Do not let one unresolved interpretation dominate
another on an invented deviation score.

The interaction policy then decides whether to ask a clarification question or
return at most K representative interpretation groups. It may use observable
impact such as different operators, answer schemas, backend capabilities, or
large predicted-cost separation to decide that a question is necessary, but it
may not call backend execution or an answer oracle to make that decision.

Advantages: preserves the existing “ask the right question” story, keeps all
bounded interpretations, and makes semantic deviation meaningful. Limitation:
the selector becomes hierarchical rather than one global three-objective
frontier, and the clarification-impact threshold must be frozen and evaluated.

### Option B — one global frontier with provenance-derived semantic loss

Assign every interpretation a scalar semantic-loss value using fixed evidence
types such as exact lexical match, ontology hop, and structural reinterpretation,
then run one global semantic-loss/latency/resource Pareto frontier.

Advantages: closest to the existing F2C9 implementation and produces one
compact frontier. Limitations: requires author-chosen weights and calibration;
it conflates ambiguity with relaxation; ontology distance is not user-intent
distance; and a reviewer can reasonably challenge the scalar as arbitrary.

### Option C — authoritative clarification before any semantic frontier

Ask the user to bind every ambiguity that changes executable semantics. After
binding, construct relaxations around that single interpretation and reuse the
existing F2C9 invariant of one zero-deviation class.

Advantages: cleanest semantic contract and smallest implementation change.
Limitations: increases interaction latency, makes the system ask even when
multiple interpretations could be returned usefully, and weakens the planned
multiple semantic-plan interface.

## Recommendation

Choose **Option A**. It is the only option that simultaneously preserves all
bounded interpretations, keeps LLM output non-authoritative, supports dynamic
clarification, and reserves `semantic_deviation` for changes relative to an
actual reference meaning. It also preserves family memory as the source of
physical-cost predictions with zero current-query profiling.

The author selected Option A on 2026-09-06. E5 must therefore use the
two-level contract below. The author subsequently selected R1, the semantic
structure gate, as the clarification-impact rule. Neither decision authorizes
a CWRU run.

## R1 — semantic structure clarification gate

E5 must ask for authoritative clarification whenever unresolved
interpretations differ in aggregation, path structure, quantification, answer
meaning, output contract, or executable capability. These are semantic or
operator-level changes, not cost differences, and family-memory predictions
cannot resolve them.

For the frozen financial-risk example, `qualifying_single_transfer`,
`window_total_amount`, and `window_transfer_count` therefore trigger one
bounded question asking whether `密切` means a qualifying single transfer,
cumulative amount within the window, or transfer frequency. A cost estimate,
candidate order, ontology hop, or non-authoritative model subset may not answer
that question.

Interpretations that preserve the same semantic-operator structure and output
contract remain eligible for bounded representative return. In the current
example, `transferred_to` and `paid_to` within one selected relationship-
strength meaning are such representatives. E5 performs physical reduction
inside each of them but assigns neither an invented semantic-deviation score.

The first offline mechanism must publish the physical representatives and the
clarification request while keeping execution unauthorized. After an explicit
in-set relationship-strength selection, it may return the two predicate
representatives, subject to K. Unselected and unavailable interpretations stay
visible in the artifact.

## Implemented offline mechanism

Commit `b2d89c4385e2f3cad138e71708cdc9ed8beae6e9` implements a new E5 schema
rather than weakening F2C9. It consumes the complete E4 bridge and a sealed
same-family training-memory view. A reusable strategy-conditioned predictor
estimates latency and transferred bytes for every executable physical target,
including its target feature record, neighbor provenance, uncertainty, and
content hash. It makes zero current-query profile, backend, model, ontology-
service, or oracle calls.

On the controlled local mechanism fixture, E5 retains all six interpretation
classes and all four physical candidates. It predicts all four plans and keeps
one physical representative for each of the two executable interpretations.
With no structural authority, it emits one relationship-strength question,
returns no execution-eligible semantic plan, and leaves every semantic
deviation null. With an explicit in-set `single transfer` selection, it returns
the two same-structure predicate representatives, one for `transferred_to` and
one for `paid_to`; the four unavailable aggregate interpretations remain in
the artifact.

The compact, hash-bound record is
`experiments/artifacts/m15_e5_local_hierarchical_interpretation_frontier_20260907.json`.
The final repository state passes 1,021 tests with 36 explicit skips. This is
controlled local mechanism evidence, not user-study evidence, semantic-quality
evidence, or performance evidence. It remains `paper_result=false`.

## Implemented anchored relaxation mechanism

E5B adds the separate anchored layer without changing the unresolved R1
artifact. It accepts only an already-authoritatively selected structural
frontier plus an explicit in-set predicate base. The LLM subset, ontology
neighbor order, family-memory cost, and candidate order cannot create that
base. The predicate selection has its own authority source and is distinct
from the earlier relationship-strength clarification.

Once the base is present, E5B validates the raw SHA-256 of the exact E3
ontology artifact sealed by E4. It admits only declared one-hop `sibling`
edges between active same-structure predicate interpretations and reads the
semantic deviation directly from that relation. In the development ontology,
`transferred_to -> paid_to` has deviation `0.25` and record provenance
`relation-predicate-001`; reverse traversal is permitted only because the
relation is explicitly bidirectional. This number is a controlled ontology
fixture value, not a calibrated user-intent probability or a domain-truth
claim.

The authoritative class receives deviation `0`; its ontology sibling receives
the declared `0.25`. The selector then performs three-objective Pareto,
semantic-preserving 5% epsilon, and K=4 reduction over this anchored set only.
It reuses the one family-memory physical representative already chosen inside
each interpretation and performs zero current-query profiling. With
`transferred_to` as base, both classes remain on the controlled frontier
because `paid_to` trades semantic deviation for lower predicted latency and
bytes. With `paid_to` as base, it dominates the more expensive relaxed
`transferred_to` class, so only the exact base is returned. All six original
E4 classes, including four unavailable aggregate meanings, remain visible.

The compact evidence record is
`experiments/artifacts/m15_e5b_local_anchored_interpretation_frontier_20260907.json`.
It binds the implementation commit, bridge, hierarchical frontier, training
memory, ontology, policy, both anchor directions, and zero-call claim boundary.
This is controlled local nonmeasurement evidence with `paper_result=false`.
The final repository acceptance run passes 1,030 tests with 36 explicit
environment/external-artifact skips; the focused E5 suite passes 20 tests.
No CWRU run is needed for this selector-only mechanism.

## Implemented clarification-to-execution transport

E5C implements the selected resumable transport without turning the UI or free
conversation into part of the optimizer. A session is reconstructed from the
sealed E4 bridge, direct workload, same-family memory view, E5/E5B policies,
the exact E4-bound ontology, a transport policy, and an ordered authority-event
log. With no event it emits the one R1 relationship-strength question. An
accepted event must select exactly one listed candidate and bind its session,
sequence, hole, pending-question hash, explicit authority source, and event
hash. It then either stops because the selected aggregate structure lacks an
executable family, or emits a second bounded question asking which active
predicate is the authoritative base for anchored relaxation.

Only the second explicit event activates E5B. The resulting selected-execution
handoff binds the session-state hash, authority-event-chain hash, anchored-
frontier hash, resolution commit, hard constraints, E4 bridge, returned-set
hash, and each attached runtime-plan hash. Its plan map contains all and only
the E5B returned plans in selection-rank order. The portable form contains no
backend-native query text and allowlists only the existing
`runtime.execute_plan` interface. A controlled integration test executes the
attached plans through that tool and verifies that no other E4 plan runs.

The event log can be persisted and replayed after a process restart; exact
reconstruction is a gate, not an advisory. Added, reordered, out-of-set,
cross-session, or text-bearing authority events fail closed. A separate
auditor independently recompiles the session and verifies the session/state/
event/handoff hashes, all-and-only plan membership, tool allowlist, native-text
absence, and zero-call claim boundary. It passes 13/13 checks. Focused adjacent
E4/E5 regression passes 43 tests and the full repository passes 1,044 tests
with 36 explicit skips.

The compact record is
`experiments/artifacts/m15_e5c_local_clarification_transport_20260907.json`.
It is controlled local nonmeasurement evidence, keeps `paper_result=false`,
and authorizes neither a CWRU run nor a user-utility or performance claim. A
future UI is only an adapter over this session/event API. A live selected-plan
gate, if needed, must be frozen separately and reuse the existing E4B native
service lifecycle without changing E5C semantics.

## Contract if Option A is selected

E5 should introduce a new schema rather than weaken the existing F2C9 schema.
Each candidate must carry:

- `interpretation_class_id` and its complete selected-candidate provenance;
- `interpretation_status`: `unresolved`, `authoritatively_bound`, or
  `unavailable`;
- `relaxation_base_id`, nullable unless an authoritative base exists;
- `semantic_deviation`, nullable for unresolved co-equal interpretations and
  required for an anchored relaxation;
- the capability decision and physical candidate IDs from E4;
- family-memory latency/byte estimates and uncertainty for every executable
  physical candidate;
- one lowest-cost physical representative per interpretation under the frozen
  physical objective;
- the clarification decision, its reason codes, and whether the returned set
  is bounded by epsilon and K.

The first implementation slice must use no backend profile, LLM, ontology
service, or answer oracle during selection. It must retain unavailable classes,
preserve all hard constraints, expose no native query text, and keep zero
automatic retry.

## Required evaluation questions

The mechanism gate must prove that:

1. reordering candidate IDs cannot change semantic authority or the returned
   interpretation identities;
2. a non-authoritative model subset cannot create a zero-deviation class;
3. family-memory estimates cover every executable physical candidate and use
   zero current-query profiling calls;
4. only the cheapest physical plan per interpretation survives physical
   reduction;
5. unanchored interpretations are never Pareto-dominated by invented semantic
   distance;
6. anchored relaxations obey Pareto, epsilon dominance, and K;
7. clarification is triggered only by a frozen, auditable impact rule;
8. all unavailable semantic classes remain visible and unexecuted;
9. oracle and post-execution measurements cannot enter selection;
10. all outputs remain development-only with `paper_result=false`.

## Author decisions

**Selected: A — two-level interpretation sets and relaxation frontiers.**

**Selected: R1 — semantic structure clarification gate.**

**Implemented: E5B — explicit predicate base followed by provenance-bound
one-hop sibling relaxation.**

**Implemented: E5C — resumable two-stage authority transport and all-and-only
selected execution handoff.**

Rejected alternatives remain recorded above so the final design cannot be
silently converted into a global provenance-weighted score, a cost-triggered
meaning choice, or an always-clarify policy after results are observed. No new
CWRU experiment is needed for this design gate. The next step is a thin UI
adapter and a separately justified live selected-plan gate; neither may change
the two explicit authority events or the existing zero-retry backend boundary.
