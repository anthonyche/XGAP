MATCH (alice:Person {name: "Alice"})-[:OWNS]->(aliceAccount:Account)
MATCH (aliceAccount)-[transfer:TRANSFER]->(companyAccount:Account)
MATCH (company:Company)-[:OWNS]->(companyAccount)
WHERE company.risk_level = "HIGH"
  AND transfer.occurred_on >= date("2026-01-01")
RETURN company.name AS company,
       transfer.amount AS amount,
       transfer.currency AS currency,
       toString(transfer.occurred_on) AS occurred_on
ORDER BY company;
