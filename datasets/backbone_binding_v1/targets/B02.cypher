MATCH (a:Person {id:"b"})-[r:KNOWS]->(p:Person) WHERE p.age >= 30 RETURN "https://xgap.test/toy/" + p.id AS person, "https://xgap.test/toy/" + r.id AS edge
