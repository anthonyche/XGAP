# Finite regex repetition witnesses

The original 5-node/8-edge graph and all previous gold stay unchanged. Thirteen
new chains contain NL, gold PathPatternQuery, independently written logical
trees, independent Cypher/SPARQL targets and explicit complete path answers.

R01–R03 cover optional composition and exactly zero repetitions, R04 applies
SHORTEST after the repetition lower bound, R05–R06 distinguish repetition count
from edge length, R07–R08 distinguish TRAIL from WALK, R09 distinguishes a
nullable child inside positive repetition from R10's separate zero-repetition
branch, R11 composes finite WALK repetition and an IN step, R12 supplies a
finite depth for an open upper bound, and R13 preserves parallel edge identity
under undirected TRAIL repetition.

Targets use independently enumerated finite branch shapes. Shortest targets
aggregate the minimum length per endpoint pair and retain all ties. They do not
call production lowering, native expansion or the coordinator selector.
All results are development correctness evidence, not benchmark accuracy.
