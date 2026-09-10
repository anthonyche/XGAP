CALL {
MATCH (n0:Person)
WHERE n0.id = "a"
MATCH (n0)-[e1:KNOWS]->(n1)
MATCH (n1)-[e2:KNOWS]->(n2)
RETURN n0.id + "/" + e1.id + "/" + n1.id + "/" + e2.id + "/" + n2.id AS path, n0.id AS start, n2.id AS finish, 2 AS length
}
RETURN DISTINCT path ORDER BY path
