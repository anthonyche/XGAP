CALL {
MATCH (n0:Person)
MATCH (n0)-[e1:KNOWS]->(n1)
RETURN n0.id + "/" + e1.id + "/" + n1.id AS path, n0.id AS start, n1.id AS finish, 1 AS length
}
RETURN DISTINCT path ORDER BY path
