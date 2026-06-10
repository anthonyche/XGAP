# XGAP Design Decisions

## D1 Logical algebra alignment

XGAP aligns its logical operator vocabulary with the path algebra from "Path-based Algebraic Foundations of Graph Query Languages".

## D2 Path-centric MVP

The MVP supports path-centric graph queries and regular path queries.

## D3 Entity grounding is outside algebra

Entity lookup, schema matching, ambiguity grounding, and disambiguation are outside the logical algebra.

## D4 No fake future features

Unimplemented future features must raise NotImplementedError.

## D5 Deterministic lowering

LLM output may propose candidate interpretations, but algebraic correctness must be guaranteed by deterministic validation and lowering.

## D6 Reference evaluator first

The in-memory reference evaluator defines executable semantics for tests and compiler validation. Backend execution comes later.

## D7 Backend configuration is separate from compiler logic

Backend capability profiles, connection information, and supported semantics should be configured separately from query compilation.

## D8 Extended algebra uses SolutionSpace

XGAP implements GroupBy, OrderBy, and Projection through a secondary data object called SolutionSpace.

Reason:

The extended path algebra uses SolutionSpace = (S, G, P, α, β, △) to express selector-style semantics. This keeps the core and recursive algebra closed over PathSet, while allowing GQL/SQL-PGQ selectors to be represented algebraically.

## D9 GroupBy does not order or remove paths

GroupByOp only organizes paths into partitions and groups. It initializes all ranks to 1.

Reason:

Ordering is the responsibility of OrderByOp, and path selection is the responsibility of ProjectionOp.

## D10 OrderBy only updates ranks

OrderByOp preserves paths, partitions, groups, path-to-group assignments, and group-to-partition assignments. It only updates the rank function.

Reason:

This follows the formal semantics of the extended algebra, where τθ(SS) returns a new solution space with the same S, G, P, α, and β, but with an updated rank function △.

## D11 Projection is deterministic in the reference evaluator

When ranks tie, ProjectionOp uses stable deterministic tie-breakers.

Reason:

Selectors such as ANY and ANY SHORTEST may be nondeterministic, but XGAP's reference evaluator must be reproducible for tests, debugging, and compiler validation.

## D12 Empty SolutionSpace canonicalization

If GroupByOp receives an empty PathSet, XGAP returns an empty SolutionSpace with no partitions and no groups.

Reason:

Projection over empty input should naturally return an empty PathSet. This avoids artificial empty partitions or groups in the reference evaluator.

## D13 Restrictors and selectors are implemented separately

Recursive modes implement path restrictors, while GroupBy, OrderBy, and Projection implement selector semantics.

Reason:

This separation matches the algebraic structure of path queries and keeps the implementation modular.

## D14 M5 uses GPC-Lite, not full GPC

XGAP M5 introduces a path-centric structured pattern layer inspired by GPC, called GPC-Lite.

Reason:

XGAP needs deterministic structured path-query intent before natural-language planning and backend compilation. Full GPC features such as assignment relations, multiple conjunctive clauses, `Maybe`, group variable semantics, bag/null semantics, full label expressions, and parser/compiler behavior are deliberately future work.

## D15 Pattern lowering emits only audited logical operators

GPC-Lite lowering maps to the existing audited XGAP logical algebra: `Nodes`, `Edges`, `Selection`, `Union`, `Join`, `Recursive`, `GroupBy`, `OrderBy`, and `Projection`.

Reason:

The pattern layer must not invent a second graph algebra. It connects structured intent to the already audited logical layer.

## D16 Direction support is staged

The M5 AST can represent `OUT`, `IN`, and `UNDIRECTED` edge directions, but M5 lowering supports only `OUT`.

Reason:

Reverse and undirected traversal require additional algebraic or graph-normalization decisions. M5 rejects those during lowering instead of silently faking unsupported behavior.
