# Necessary split-source tiny development fixture

Four people exist only in Neo4j profiles. Fuseki relations contains four identity stubs and three directed edges, without ages, names or Person types. Both use the split identity namespace. No store alone can answer the age-filtered relation question.

The frozen catalog contains all four names, schema/source vocabulary and integer literals 0..100. It is prepared offline. The inference request contains original NL and reusable source schema only; no operator IDs, structured output or hard constraints, program, gold or target queries. Gold files are independent checks, excluded from inference dependencies. This is one tiny integration request, not a benchmark or a generalization sample.
