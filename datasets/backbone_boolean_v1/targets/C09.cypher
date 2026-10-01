MATCH (n)-[e]->(m)
WHERE coalesce(e.weight IN [1, true], false) OR type(e) <> "KNOWS"
RETURN DISTINCT n.id + "/" + e.id + "/" + m.id AS path
