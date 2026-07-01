CREATE CONSTRAINT company_id IF NOT EXISTS
FOR (c:Company)
REQUIRE c.id IS UNIQUE;

CREATE CONSTRAINT person_id IF NOT EXISTS
FOR (p:Person)
REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT account_id IF NOT EXISTS
FOR (a:Account)
REQUIRE a.id IS UNIQUE;

MERGE (alice:Person {id: "person-alice"})
SET alice.name = "Alice";

MERGE (aliceAccount:Account {id: "acct-alice"})
SET aliceAccount.opened_on = date("2024-01-10");

MERGE (redstone:Company {id: "company-redstone"})
SET redstone.name = "Redstone Analytics",
    redstone.risk_level = "HIGH";

MERGE (blackpeak:Company {id: "company-blackpeak"})
SET blackpeak.name = "BlackPeak Trading",
    blackpeak.risk_level = "HIGH";

MERGE (blueharbor:Company {id: "company-blueharbor"})
SET blueharbor.name = "Blue Harbor Logistics",
    blueharbor.risk_level = "LOW";

MERGE (redstoneAccount:Account {id: "acct-redstone"});
MERGE (blackpeakAccount:Account {id: "acct-blackpeak"});
MERGE (blueharborAccount:Account {id: "acct-blueharbor"});

MERGE (alice)-[:OWNS]->(aliceAccount);
MERGE (redstone)-[:OWNS]->(redstoneAccount);
MERGE (blackpeak)-[:OWNS]->(blackpeakAccount);
MERGE (blueharbor)-[:OWNS]->(blueharborAccount);

MERGE (aliceAccount)-[t1:TRANSFER {id: "transfer-001"}]->(redstoneAccount)
SET t1.amount = 125000,
    t1.currency = "USD",
    t1.occurred_on = date("2026-03-12");

MERGE (aliceAccount)-[t2:TRANSFER {id: "transfer-002"}]->(blackpeakAccount)
SET t2.amount = 87000,
    t2.currency = "USD",
    t2.occurred_on = date("2026-04-02");

MERGE (aliceAccount)-[t3:TRANSFER {id: "transfer-003"}]->(blueharborAccount)
SET t3.amount = 43000,
    t3.currency = "USD",
    t3.occurred_on = date("2026-04-15");

MERGE (aliceAccount)-[t4:TRANSFER {id: "transfer-004"}]->(redstoneAccount)
SET t4.amount = 12000,
    t4.currency = "USD",
    t4.occurred_on = date("2024-05-20");
