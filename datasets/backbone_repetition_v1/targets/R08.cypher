CALL {
MATCH (n0)-[e1:KNOWS]->(n1)
MATCH (n1)-[e2:KNOWS]->(n2)
WHERE n0.id = "d" AND n2.id = "d"
RETURN n0.id + "/" + e1.id + "/" + n1.id + "/" + e2.id + "/" + n2.id AS path, n0.id AS src, n2.id AS dst, 2 AS length
}
RETURN DISTINCT path
