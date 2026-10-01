CALL {
MATCH (n0:Person)
WHERE n0.id = "b"
MATCH (n1)-[e1:KNOWS]->(n0)
RETURN n0.id + "/" + e1.id + "/" + n1.id AS path, n0.id AS start, n1.id AS finish, 1 AS length
}
RETURN DISTINCT path ORDER BY path
