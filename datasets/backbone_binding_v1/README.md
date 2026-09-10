# Tiny semantic binding fixture v1

This frozen, hand-authored development fixture uses the unchanged five nodes
and eight edges in `../backbone_toy_v1/`. No GrailQA data or model is required.

Each case contains NL, a partially bound semantic DAG, gold path subquery
(null for the node-only B04), expected logical plan, independent Cypher/SPARQL
targets, and typed expected rows. Existing 18 path and eight composition gold
cases are unchanged. These cases test the Interpretation interface plus binding;
they do not measure NL parsing accuracy. B05's user choice is a controlled
fixture, not a claim that a real person answered during the test.

| Case | Input change | Independent answer |
|---|---|---|
| B01 | Alice, knows, people, age >= 30, toy source | Cara via e4 |
| B02 | Bob instead of Alice | Cara via e2 |
| B03 | Alice with age >= 45 | empty set |
| B04 | Match Alice, age >= 30 | a, age 30 |
| B05 | ambiguous Alex, explicit fixture choice Bob | Cara via e2 |

`catalog.json` is authored offline and read with the existing artifact provider.
`bindings.json` declares typed candidate-to-value mappings; neither file is
built or expanded at query runtime. The data and catalog are tiny development
inputs, not evaluation-derived inference context. Source `toy` denotes the
same complete frozen graph on each explicitly declared backend replica.

Entity slots occupy positive node-identity descriptors or conjunctive equality
predicates. This binding profile deliberately rejects identity slots under NOT
or OR, output aliases, or unused declarations. Predicate/type slots bind schema
labels; constraint slots bind finite scalar values; source slots bind logical
source declarations. Native compilation enforces named structured constraints
together with existing query conditions. No hard or relaxable constraint is
automatically dropped. Human-readable opaque requirements remain unsupported.

The native gate resolves, binds, observes unique fragments, selects one plan,
and executes it through the existing bounded GoalLoop. It then validates other
placements and both independent native targets separately from serving cost.
Original cross-backend T18 remains the final vertical-slice check. All results
are correctness evidence only, with no live LLM, no retries, and no paper claim.
