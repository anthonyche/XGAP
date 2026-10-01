# Backbone toy v1

Five people, eight KNOWS edges, 18 complete gold-chain queries. These are open
unit/integration fixtures, not benchmark predictions. IDs a/b/c/d/z identify
Alice/Bob/Cara/Dan/Zoe. e1 and e7 are distinct a→b edges; a→b→c→a is a cycle;
e6 is d→d; z is isolated. Ages are 30/22/40/19/50.

`queries.json` contains the independently authored expected path strings. A path
alternates node and edge IDs separated by `/`; its stable order is the full
alternating sequence, not just node IDs. ANY selectors use that stable order.
The target queries are independent bounded reference programs, not snapshots
of the XGAP compiler. Successful target execution does not establish compiler
support. Cypher uses one MATCH clause per step to permit WALK edge reuse. RDF
uses edge resources to preserve parallel edge identity and ordinary KNOWS
triples for current compiler diagnostics; these have different identity power.

T15 records its intended semantic Traverse plan; the old M5 path-algebra
lowerer cannot lower IN, which remains an explicit T1 gap. All other logical
expectations are exact path-algebra trees. GroupBy means the path-algebra
SolutionSpace operation, not SQL COUNT. T18 carries a federated placement;
T04 is the same meaning without a prescribed placement. The deterministic
chain consumes these gold programs directly. Interpretation tests compare NL
outputs against them separately. No LLM or GrailQA preprocessing is used.

Daily checks: `PYTHON=python bash scripts/run_toy_development.sh` from the
repository root. The RDF execution checks require the `test-sparql` optional
dependency; a skipped optional engine is not native correctness evidence.
Coverage report: `python -m xgap.experiments.toy_backbone --output new-report.json`.
The report retains unavailable lowering/compiler rows and never claims full
backbone completion merely because reporting succeeded.

Real two-engine checks use `scripts/run_toy_backbone_native.py --help`. They
require prepared native binaries and an explicit new owned output directory;
they start only tiny fresh stores and never load a GrailQA/Freebase snapshot.
