MATCH (n0)-[e1:KNOWS]-(n1)
MATCH (n1)-[e2:KNOWS]-(n2)
WHERE n0.id = "b" AND n2.id = "b" AND n0 <> n1 AND n0 <> n2 AND n1 <> n2
RETURN DISTINCT n0.id + "/" + e1.id + "/" + n1.id + "/" + e2.id + "/" + n2.id AS path
