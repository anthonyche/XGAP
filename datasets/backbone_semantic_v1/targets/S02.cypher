MATCH ()-[r:KNOWS]->(p:Person) WHERE p.age >= 20 WITH p, count(r) AS n RETURN "https://xgap.test/toy/" + p.id AS person, n ORDER BY n DESC, person ASC LIMIT 2
