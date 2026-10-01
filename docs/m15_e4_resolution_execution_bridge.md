# M15-E4 Resolution-to-Executable-Class Bridge

## Status

M15-E4 is implemented locally as a capability-aware development bridge. It
consumes the immutable output of M15-E3, enumerates the complete bounded
semantic cross-product, checks every class against a hash-bound executable
family package, and creates physical candidates only for classes whose full
semantics are available. It makes no model or backend call and remains
`paper_result=false`.

## Why a bridge is necessary

A candidate ID is not an executable query. Resolution may produce meanings
that the current backend templates cannot express. Treating an approximately
similar slot as equivalent would silently alter the request.

The controlled request exposes two concrete examples:

- `过去一个月` means both `occurred_on >= 2026-08-01` and
  `occurred_on < 2026-09-01`; the original F2C family had only a lower-bound
  parameter;
- a window-total amount condition is not equivalent to filtering each
  individual transfer by amount, and a window-frequency condition requires a
  count/threshold capability that the family does not have.

E4 therefore models availability as a proof obligation over named
capabilities. A class with any missing capability stays in the output with an
explicit reason and receives no physical plan.

## Controlled interpretation space

E3 preserves three possible meanings for `密切`:

1. at least one transfer of at least 50,000 USD;
2. total amount in the window of at least 50,000 USD;
3. at least three transfers in the window.

Together with two transfer-predicate candidates and one resolved risk type,
this creates six raw interpretations. The authoritative `Alice Smith`
selection and both calendar-window bounds are identical in all six classes.
Class identity is a content hash of the complete canonical semantics, so
candidate and hole ordering cannot change equivalence-class identity.

The current capability result is:

| relationship-strength interpretation | predicates | status | reason |
| --- | ---: | --- | --- |
| qualifying single transfer | 2 | executable | all capabilities registered |
| window total amount | 2 | unavailable | no window `SUM` threshold |
| window transfer count | 2 | unavailable | no window `COUNT/HAVING` threshold |

No interpretation is silently removed. The two executable classes each obtain
the registry's `parallel_hash_join` and `risk_first_bind_join` strategies, for
four physical candidates total.

## Exact calendar-window extension

The parent F2C family already registers identity, lower-time, per-edge amount,
risk, predicate, path, Fuseki, and physical-strategy contracts. E4 adds two
small bridge-owned Neo4j templates for full and bound execution. Both are raw
SHA-256 bound in the bridge specification and add the missing exclusive upper
bound as a runtime parameter. Compilation validates the complete compile-token
and runtime-parameter sets before constructing a plan.

This is an external black-box query-template extension. It does not modify or
inspect Neo4j internals and does not retroactively change any earlier F2C
artifact. The emitted plan description contains hashes, plan IDs, strategy
IDs, and template roles but not native query text. The in-memory runtime plans
retain the registered text needed for later execution.

## Integrity gates

Compilation fails before producing output when any of the following occurs:

- E3 artifact, hard-constraint, authoritative-entity, or resolution-commit
  identity drifts;
- a sealed candidate lacks exactly one declared bridge mapping;
- the semantic cross-product exceeds its finite bound;
- a claimed family capability lacks matching registry or template evidence;
- a missing capability has no explicit reason;
- an executable class does not bind every parent-family and extension slot;
- a class does not map to exactly one registered semantic task;
- physical candidates differ from the registry's strategy set.

The offline execution test uses deterministic fixture oracles only after plan
construction to verify that all four generated plans return the exact answer.
Oracle rows are absent from bridge selection and output.

The bridge/E3/registry-focused gate passes 32 tests. Full local acceptance
passes 1,003 tests with 36 explicitly gated skips.

## Artifacts and example

- `experiments/configs/m15_e4_resolution_execution_bridge_dev.json`
- `experiments/templates/m15_e4_financial_risk_window/neo4j_full.cypher.tmpl`
- `experiments/templates/m15_e4_financial_risk_window/neo4j_bound.cypher.tmpl`
- `examples/m15_resolution_execution_bridge_demo.py`

Run locally with:

```bash
PYTHONPATH=src python examples/m15_resolution_execution_bridge_demo.py
```

## Limits and next gate

E4 proves deterministic semantic-to-capability binding for one controlled
family. It does not rank the two executable interpretations, estimate their
cost, execute live services, implement window aggregation, or establish
open-domain coverage. M15-E4B now supplies the separate native execution
lifecycle and independent evidence audit for the four plans; see
[`docs/m15_e4b_live_resolution_execution.md`](m15_e4b_live_resolution_execution.md).
It still does not add `SUM` or `COUNT/HAVING`: those operators/templates should
be admitted only through the benchmark query-family design rather than silently
synthesized from an unavailable interpretation.
