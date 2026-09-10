CALL {
MATCH (n0:Person)
RETURN n0.id AS path, n0.id AS start, n0.id AS finish, 0 AS length
}
RETURN DISTINCT path ORDER BY path
