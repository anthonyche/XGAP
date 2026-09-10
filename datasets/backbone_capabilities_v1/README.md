# Capability requirements on the existing tiny graph

These eight explicit overlays reuse the complete independently authored chains
in backbone_semantic_v1 (NL, semantic DAG with PathPatternQuery, expected runtime
plan, target queries and typed rows). They do not modify those fixtures or the
5-node/8-edge graph. cases.json adds required capabilities and independently
enumerated allowed placements; it is never read by production admission.

C01/C08 force opposite actual two-engine placements. C02 retains all four
placements while requiring coordinator aggregation, ordering and filtering.
C03 witnesses a Traverse's own semi-join. C04 tests shared-source fan-out and
union. C05 retains the empty global count. C06 tests alignment and the existing
equality_join alias; C07 tests join column collisions across all four placements.

Expected: 16 admitted placements out of the original 28; the remaining 12 are
rejected before observation registration. All admitted candidates retain the
base case's exact typed answers. Counts are development correctness witnesses,
not new independent benchmark questions or optimizer performance evidence.
