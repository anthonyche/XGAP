# Total scalar Boolean fixture v1

Separate property overlay on the original five nodes/eight edges. Original
backbone_toy_v1 graph, load files and gold are unchanged. No LLM/catalog/GPU is
required. This is correctness evidence, not a held-out question-answering set.

| Node | score | note | flag | floor |
|---|---|---|---|---|
| a | integer 1 | open | boolean true | signed 64-bit minimum |
| b | double 1.0 | closed | boolean false | absent |
| c | boolean true | absent | integer 1 | absent |
| d | string "1" | open | integer 0 | absent |
| z | absent | absent | absent | absent |

Edge weight: e1 integer1, e7 double1.0, e2 boolean true, e3 string"1",
e5 integer0, e8 boolean false; e4/e6 absent. RDF floating values are explicit
xsd:double (1.0e0), not decimal, consistent with the JSON/property-graph float.

20 independently authored NL → PathPatternQuery → logical tree → native
reference → complete path chains cover equality, inequality, NOT, OR, nested
AND/NOT, missing properties, node/edge labels, identity, boolean/numeric scalar
rules, numeric ordering, isolated zero paths, and shortest-before-outer-length
filtering. Expected plans and answers were not obtained from XGAP compilation
or evaluation. Match has four explicit programs/typed answers and eight native
reference targets. Ordinary planning checks use C04/C14/M01.

C14/C15 have zero answers: first choose the shortest paths for an endpoint pair,
then apply the outer Boolean length filter. Longer paths must not be promoted.
C16 has one direct path; its endpoint-only disjunction can move before minimum
selection. C17 keeps all five nodes under NOT Ghost. C20 must retain the signed
64-bit minimum without evaluating overflowing abs(minimum) in Cypher.

Independent Cypher shortest references collect paths and select the minimum
before filtering. Independent SPARQL enumerates one/two/three edges and excludes
shorter connectivity, then applies the outer filter. They do not use production
native renderers. Early local aggregate/correlated-filter versions did not pass
RDFLib; those failures remain in the development logs, not accepted references.

`rejected.json` retains an exploratory numeric-position predicate on variable
length recursion. Existing semantic admission rejects that query before native
or scoped compilation; no claim that this gap was implemented. The original
C17 draft was moved to this negative replay instead of weakening admission or
changing its semantic answer.

Portable scalar assumptions: one logical value per mapped property; integers,
finite floating values, booleans and strings. Python reference equality retains
True=1 and False=0. Numeric ordering excludes booleans/non-numeric data. Missing
property equality and inequality are both false, so NOT equality differs from
inequality. Arbitrary multivalued RDF properties, null query constants and
language/date/decimal projection policies are outside this fixture's claim.

Run focused: `pytest tests/test_native_boolean_conditions.py`.
Run owned native stores: `scripts/run_toy_backbone_native.py --boolean --execute`
with explicit prepared runtime, Java21 and a fresh output directory. All source
and fixture hashes, calls, terminal errors and shutdown results are recorded.
The original two-backend slice is retained on the unchanged original fields.
