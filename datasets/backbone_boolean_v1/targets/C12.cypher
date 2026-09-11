MATCH (n)-[e]->(m)
WHERE CASE WHEN e.weight IS :: INTEGER NOT NULL OR e.weight IS :: FLOAT NOT NULL THEN e.weight >= 0 ELSE false END
RETURN DISTINCT n.id + "/" + e.id + "/" + m.id AS path
