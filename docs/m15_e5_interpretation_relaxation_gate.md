# M15-E5 Interpretation–Relaxation Objective Gate

## Status

**OPTION A AND R1 SELECTED; OFFLINE MECHANISM IMPLEMENTATION ACTIVE; NO CWRU RUN AUTHORIZED**

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

Rejected alternatives remain recorded above so the final design cannot be
silently converted into a global provenance-weighted score, a cost-triggered
meaning choice, or an always-clarify policy after results are observed. No new
CWRU experiment is needed for this design gate; the next step is the offline
mechanism and invariant suite.
