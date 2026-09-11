MATCH (n:Person)
WHERE NOT coalesce(n.score IN [1, true], false)
RETURN DISTINCT n.id AS path
