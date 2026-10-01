CALL {
CALL {
MATCH (n0)-[e1:KNOWS]->(n1)
RETURN DISTINCT n0.id + "/" + e1.id + "/" + n1.id AS path, n0.id AS src, n1.id AS dst, 1 AS length
UNION
MATCH (n0)-[e1:KNOWS]->(n1)
MATCH (n1)-[e2:KNOWS]->(n2)
WHERE n0 <> n1 AND n1 <> n2
RETURN DISTINCT n0.id + "/" + e1.id + "/" + n1.id + "/" + e2.id + "/" + n2.id AS path, n0.id AS src, n2.id AS dst, 2 AS length
}
WITH path AS lp, src AS ls, dst AS ld, length AS ll
CALL {
MATCH (n0)<-[e1:KNOWS]-(n1)
RETURN DISTINCT n0.id + "/" + e1.id + "/" + n1.id AS path, n0.id AS src, n1.id AS dst, 1 AS length
}
WITH * WHERE ld = src
RETURN DISTINCT lp + substring(path, size(src)) AS path, ls AS src, dst, ll + length AS length
}
WITH * WHERE src = "d" AND dst = "d"
RETURN DISTINCT path
