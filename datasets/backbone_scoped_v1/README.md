# Scoped finite path witnesses

Fifteen independent complete chains use the unchanged 5-node/8-edge toy graph.
N01–N05 separate local path modes from an enclosing restriction. N06–N07 retain
zero branches around shortest scopes. N08 covers variable child lengths.
N09–N10 apply an outer length condition after local shortest selection.
N11–N12 compose Union/Optional and empty local results. N13 reuses one shortest
child twice, N14 composes reverse TRAIL with forward edges, and N15 covers
finite nested WALK. Gold logical trees and full identity answers were manually
specified, not captured from production output. Independent native targets use
relational subqueries and per-scope minimum-length aggregation.

This is development correctness evidence, not benchmark accuracy or performance.
