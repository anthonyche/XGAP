CALL {
MATCH (n0:Person)
WHERE n0.id = "d" AND n0.id = "d"
RETURN n0.id AS path, n0.id AS src, n0.id AS dst, 0 AS length
UNION
MATCH (n0)-[e1:KNOWS]->(n1)
WHERE n0.id = "d" AND n1.id = "d"
RETURN n0.id + "/" + e1.id + "/" + n1.id AS path, n0.id AS src, n1.id AS dst, 1 AS length
UNION
MATCH (n0)-[e1:KNOWS]->(n1)
MATCH (n1)-[e2:KNOWS]->(n2)
WHERE n0.id = "d" AND n2.id = "d"
RETURN n0.id + "/" + e1.id + "/" + n1.id + "/" + e2.id + "/" + n2.id AS path, n0.id AS src, n2.id AS dst, 2 AS length
}
WITH src, dst, min(length) AS minimum, collect({path:path, length:length}) AS candidates
UNWIND candidates AS candidate
WITH candidate, minimum WHERE candidate.length = minimum
RETURN DISTINCT candidate.path AS path
