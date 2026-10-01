CALL {
MATCH (n0:Person)
WHERE n0.id = "z"
RETURN n0.id AS path, n0.id AS src, n0.id AS dst, 0 AS length
}
RETURN DISTINCT path
