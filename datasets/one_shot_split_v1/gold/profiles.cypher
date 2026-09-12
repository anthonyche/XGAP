MATCH (p:Person) WHERE p.age >= 30 RETURN p.id AS person, p.age AS age;
