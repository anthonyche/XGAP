CALL {
MATCH (n0:Person)
WHERE n0.id = "a"
RETURN n0.id AS path, n0.id AS src, n0.id AS dst, 0 AS length
UNION
MATCH (n0)-[e1:KNOWS]->(n1)
WHERE n0.id = "a"
RETURN n0.id + "/" + e1.id + "/" + n1.id AS path, n0.id AS src, n1.id AS dst, 1 AS length
}
RETURN DISTINCT path
