# GrailQA Interpretation Contract Audit

## Decision Rule

The model proposes question-dependent semantic choices. A deterministic
normalizer supplies representation conventions that follow from an explicit
fixed-path profile. Backend and physical details remain outside
`PathPatternQuery`. This does not make different relations, directions,
filters, focus choices, or path semantics equivalent.

| Field | Class | M13-E1 Contract |
|---|---|---|
| Entity IDs | Semantic | Chosen from prompt-visible public entity candidates. |
| Relation IDs and sequence | Semantic | Chosen per bounded hop slot. |
| Relation direction | Semantic | `OUT`, `IN`, and `UNDIRECTED` remain distinct. |
| Path topology/length | Semantic | The model chooses the actual fixed path; no gold length is injected. |
| Endpoint type constraints | Semantic | Selected from visible type/domain-range context. |
| Explicit NL comparisons | Semantic | Emitted through the typed recursive condition grammar. |
| Source/target answer focus | Semantic | Orientation and anchored endpoint remain significant. |
| `selector=ALL` | Canonical default | Omitted means all matching paths in the fixed-path profile; an explicit non-default selector remains semantic. |
| `restrictor=SIMPLE` | Canonical profile default | The supported fixed graph-pattern profile uses SIMPLE; any explicit alternative remains semantic. |
| Pairwise `node_not_equals` | Deterministic canonicalization | Derived for all node pairs after SIMPLE and fixed path topology are known. The model must not emit it. |
| Variable names | Canonical | Ignored by equivalence. |
| Condition child ordering | Canonical | Conjunct/disjunct order is normalized; Boolean structure is preserved. |
| `max_depth` | Semantic safety bound for recursion | Null for this fixed finite fragment. It is not inferred as a physical plan parameter. |
| Backend, placement, cost, native query | Execution-related | Forbidden from model output and absent from interpretation equivalence. |

## Canonicalization

`xgap.experiments.interpretation_contract.normalize_interpretation` applies a
named `xgap-fixed-path-pattern-v1` profile. It defaults omitted selector and
restrictor fields, derives SIMPLE inequalities only for a deterministic
`Rel`/`Seq` fixed path, removes duplicate canonical inequalities from the
model/reference representation, sorts commutative condition children, and
scrubs variable spelling. It then parses the result through the existing
typed `PathPatternQuery` parser.

No dataset-name branch exists in the core. The old M13-D parser and model
bundle remain unchanged.

## Structured Condition Repair

The v1 schema declared condition as an unconstrained object. The v2 model
bundle defines discriminated recursive alternatives for label equality,
property equality/inequality/order, path-length equality, `and`, `or`, and
`not`. Python validation accepts the same grammar. `node_not_equals` is absent
from model output and rejected before normalization.

The prompt/schema change is a correctness repair. It includes no examples,
pilot-error hints, model switch, temperature change, or tuning.

## Equivalence

Headline interpretation correctness is equality after the deterministic
normalization above. Component diagnostics separately compare entity
grounding, relation sequence, direction, path structure, types, explicit
constraints, focus, selector, restrictor, and canonical conditions. The full
criterion remains strict over genuine semantics.

