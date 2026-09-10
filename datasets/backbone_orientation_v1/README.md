# Tiny orientation fixtures v1

Frozen development expectations on the unchanged graph in backbone_toy_v1.
Each of nine cases has NL, gold PathPatternQuery, independently authored logical
plan, independent Cypher/SPARQL target, and complete expected path identities.
No model, catalog builder or benchmark data is used.

| Case | Witness | Complete path count |
|---|---|---:|
| D01 | Bob IN, preserve parallel edges | 2 |
| D02 | Bob IN then OUT to Cara | 2 |
| D03 | Undirected Dan self-loop deduplicated | 1 |
| D04 | Bob one hop in either direction | 4 |
| D05 | Undirected WALK, positive closure <=2, Bob to Bob | 6 |
| D06 | Same with TRAIL, distinct parallel-edge return allowed | 2 |
| D07 | Same with ACYCLIC, repeated endpoint forbidden | 0 |
| D08 | Same with SHORTEST, all six shortest positive cycles | 6 |
| D09 | Isolated Zoe inverse Star includes the zero path | 1 |

For D05-D08 the graph has no one-step Bob self-loop. Their independent native
targets therefore enumerate two steps directly. Separate Cypher MATCH clauses
allow WALK to reuse an edge; explicit conditions enforce TRAIL/ACYCLIC. Native
production compiles the declared bounded closure. Full path identities, not
only endpoint sets, are compared. The zero-length D09 witness is node-only in
its independent targets.

`legacy_logical_plans.json` is an explicit development-only overlay for T15's
former semantic-level placeholder. It adds the hand-authored Reverse plan and
does not alter any file, NL, meaning or expected answer in backbone_toy_v1.
The development example/test opts into it; the offline CLI accepts it through
`--logical-expectations`. A run without it still compares with the original
placeholder and reports that logical mismatch, preserving legacy provenance.
Production compilers never read this gold overlay.

Reverse is defined in docs/decisions/path_orientation_v1.md. It is an explicit
XGAP orientation extension, not a redefinition of Edges(G). The older M9
compiler remains an OUT-only profile; its unsupported Reverse result is distinct
from the supported production bounded native path compiler.
