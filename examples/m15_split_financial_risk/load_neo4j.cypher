CREATE CONSTRAINT m15_person_id IF NOT EXISTS
FOR (p:M15Person)
REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT m15_account_id IF NOT EXISTS
FOR (a:M15Account)
REQUIRE a.id IS UNIQUE;

CREATE CONSTRAINT m15_company_id IF NOT EXISTS
FOR (c:M15CompanyRef)
REQUIRE c.id IS UNIQUE;

MERGE (alice:M15Person {id: "person-alice-smith"})
SET alice.name = "Alice Smith";

MERGE (aliceAccount:M15Account {id: "acct-alice"});
MERGE (c1Account:M15Account {id: "acct-c1"});
MERGE (c2Account:M15Account {id: "acct-c2"});
MERGE (c3Account:M15Account {id: "acct-c3"});

MERGE (c1:M15CompanyRef {id: "C1"});
MERGE (c2:M15CompanyRef {id: "C2"});
MERGE (c3:M15CompanyRef {id: "C3"});

MATCH (alice:M15Person {id: "person-alice-smith"})
MATCH (aliceAccount:M15Account {id: "acct-alice"})
MERGE (alice)-[:M15_OWNS]->(aliceAccount);

MATCH (c1:M15CompanyRef {id: "C1"})
MATCH (c1Account:M15Account {id: "acct-c1"})
MERGE (c1)-[:M15_OWNS]->(c1Account);

MATCH (c2:M15CompanyRef {id: "C2"})
MATCH (c2Account:M15Account {id: "acct-c2"})
MERGE (c2)-[:M15_OWNS]->(c2Account);

MATCH (c3:M15CompanyRef {id: "C3"})
MATCH (c3Account:M15Account {id: "acct-c3"})
MERGE (c3)-[:M15_OWNS]->(c3Account);

MATCH (aliceAccount:M15Account {id: "acct-alice"})
MATCH (c1Account:M15Account {id: "acct-c1"})
MERGE (aliceAccount)-[t:M15_TRANSFER {id: "m15-transfer-001"}]->(c1Account)
SET t.amount = 120000,
    t.currency = "USD",
    t.occurred_on = date("2026-08-20");

MATCH (aliceAccount:M15Account {id: "acct-alice"})
MATCH (c2Account:M15Account {id: "acct-c2"})
MERGE (aliceAccount)-[t:M15_TRANSFER {id: "m15-transfer-002"}]->(c2Account)
SET t.amount = 90000,
    t.currency = "USD",
    t.occurred_on = date("2026-08-25");

MATCH (aliceAccount:M15Account {id: "acct-alice"})
MATCH (c3Account:M15Account {id: "acct-c3"})
MERGE (aliceAccount)-[t:M15_TRANSFER {id: "m15-transfer-003"}]->(c3Account)
SET t.amount = 75000,
    t.currency = "USD",
    t.occurred_on = date("2026-07-01");
