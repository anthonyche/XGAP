MATCH (n)-[e]->(m)
WHERE NOT coalesce(e.weight IN [1, true], false)
RETURN DISTINCT n.id + "/" + e.id + "/" + m.id AS path
