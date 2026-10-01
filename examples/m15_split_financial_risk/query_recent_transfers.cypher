MATCH (person:M15Person {id: "person-alice-smith"})-[:M15_OWNS]->(source:M15Account)
MATCH (source)-[transfer:M15_TRANSFER]->(target:M15Account)
MATCH (company:M15CompanyRef)-[:M15_OWNS]->(target)
WHERE transfer.occurred_on >= date("2026-08-05")
  AND transfer.amount >= 50000
RETURN person.id AS person_id,
       person.name AS person,
       "neo:" + company.id AS company_id,
       transfer.amount AS amount,
       transfer.currency AS currency,
       toString(transfer.occurred_on) AS occurred_on
ORDER BY company_id;
