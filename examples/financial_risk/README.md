# Financial Risk Toy Dataset

This tiny dataset is for backend smoke testing only. It supports the
question:

```text
Find high-risk companies connected to Alice by recent transfers.
```

The Neo4j and Fuseki versions contain the same facts:

- Alice owns an account.
- Alice's account has recent transfers to accounts owned by high-risk
  companies.
- Alice also has older or lower-risk transfers so the smoke query checks
  both the risk and recency predicates.

Files:

- `load_neo4j.cypher`: idempotent Neo4j load script.
- `load_fuseki.ttl`: RDF/Turtle load file for Fuseki.
- `smoke_neo4j.cypher`: Neo4j smoke query.
- `smoke_fuseki.rq`: SPARQL smoke query.

Expected smoke result: at least `Redstone Analytics` and
`BlackPeak Trading` are returned.
