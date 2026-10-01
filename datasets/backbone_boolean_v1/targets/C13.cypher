MATCH (n)-[e]->(m)
WHERE n = m
RETURN DISTINCT n.id + "/" + e.id + "/" + m.id AS path
