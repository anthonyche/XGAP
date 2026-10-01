CALL {
CALL {
MATCH (n0)-[e1:KNOWS]->(n1)
RETURN DISTINCT n0.id + "/" + e1.id + "/" + n1.id AS path, n0.id AS src, n1.id AS dst, 1 AS length
UNION
MATCH (n0)-[e1:KNOWS]->(n1)
MATCH (n1)-[e2:KNOWS]->(n2)
RETURN DISTINCT n0.id + "/" + e1.id + "/" + n1.id + "/" + e2.id + "/" + n2.id AS path, n0.id AS src, n2.id AS dst, 2 AS length
UNION
MATCH (n0)-[e1:KNOWS]->(n1)
MATCH (n1)-[e2:KNOWS]->(n2)
MATCH (n2)-[e3:KNOWS]->(n3)
RETURN DISTINCT n0.id + "/" + e1.id + "/" + n1.id + "/" + e2.id + "/" + n2.id + "/" + e3.id + "/" + n3.id AS path, n0.id AS src, n3.id AS dst, 3 AS length
UNION
MATCH (n0)-[e1:KNOWS]->(n1)
MATCH (n1)-[e2:KNOWS]->(n2)
MATCH (n2)-[e3:KNOWS]->(n3)
MATCH (n3)-[e4:KNOWS]->(n4)
RETURN DISTINCT n0.id + "/" + e1.id + "/" + n1.id + "/" + e2.id + "/" + n2.id + "/" + e3.id + "/" + n3.id + "/" + e4.id + "/" + n4.id AS path, n0.id AS src, n4.id AS dst, 4 AS length
}
WITH src, dst, min(length) AS best, collect({p:path,l:length}) AS answers
UNWIND answers AS answer
WITH * WHERE answer.l = best
RETURN DISTINCT answer.p AS path, src, dst, best AS length
}
WITH * WHERE src = "a" AND dst = "c"
RETURN DISTINCT path
