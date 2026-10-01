MATCH (n)-[e]->(m)
WHERE e.weight IS NOT NULL AND NOT coalesce(e.weight IN [1, true], false)
RETURN DISTINCT n.id + "/" + e.id + "/" + m.id AS path
