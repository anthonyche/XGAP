MATCH (p:Person) WHERE p.age < 25 OR p.age >= 40 RETURN DISTINCT "https://xgap.test/toy/" + p.id AS person
