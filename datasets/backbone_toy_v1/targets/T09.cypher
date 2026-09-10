CALL {
MATCH (n0:Person)
WHERE n0.id = "a"
MATCH (n0)-[e1:KNOWS]->(n1)
WITH * WHERE n0 <> n1
RETURN n0.id + "/" + e1.id + "/" + n1.id AS path, n0.id AS start, n1.id AS finish, 1 AS length
UNION
MATCH (n0:Person)
WHERE n0.id = "a"
MATCH (n0)-[e1:KNOWS]->(n1)
MATCH (n1)-[e2:KNOWS]->(n2)
WITH * WHERE n0 <> n1 AND n0 <> n2 AND n1 <> n2
RETURN n0.id + "/" + e1.id + "/" + n1.id + "/" + e2.id + "/" + n2.id AS path, n0.id AS start, n2.id AS finish, 2 AS length
UNION
MATCH (n0:Person)
WHERE n0.id = "a"
MATCH (n0)-[e1:KNOWS]->(n1)
MATCH (n1)-[e2:KNOWS]->(n2)
MATCH (n2)-[e3:KNOWS]->(n3)
WITH * WHERE n0 <> n1 AND n0 <> n2 AND n0 <> n3 AND n1 <> n2 AND n1 <> n3 AND n2 <> n3
RETURN n0.id + "/" + e1.id + "/" + n1.id + "/" + e2.id + "/" + n2.id + "/" + e3.id + "/" + n3.id AS path, n0.id AS start, n3.id AS finish, 3 AS length
}
RETURN DISTINCT path ORDER BY path
