# Frozen resolution bundle for the existing five agent toy queries

The snapshot was explicitly published offline from the unchanged
`backbone_binding_v1/catalog.json` and `bindings.json`, using
`python -m xgap.catalog.build`. These files contain catalog candidates and their
typed executable values, not evaluation answers or native target queries.

`reference.json` is caller-owned configuration. It pins the relative snapshot
path and its expected content version. The query entry reads this prepared
snapshot only; it does not build or access the original preparation inputs.
Catalog/ontology candidate IDs and binding kinds are checked together before
any backend dispatch. Inference uses the same pre-existing authority rules.

The original NL programs, independent gold bindings/results and Cypher/SPARQL
references stay in `backbone_binding_v1`. Native verification reuses those five
queries and the permanent original two-engine slice. This is controlled
Interpretation/interface correctness, not real-model NL accuracy. Optional
ontology publication is separately tested with a tiny authored schema.

An intentional update is a new offline publication and an explicit reference
change. The publisher never overwrites this directory. Missing/incompatible
preparation is an error, never an instruction to rebuild in runtime.
