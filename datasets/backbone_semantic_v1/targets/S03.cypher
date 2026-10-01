MATCH (p:Person {id:"b"}) MATCH (p)-[r:KNOWS]->(q) RETURN [p.id,r.id,q.id] AS path
