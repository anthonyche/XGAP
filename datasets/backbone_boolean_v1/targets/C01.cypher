MATCH (n:Person)
WHERE coalesce(n.score IN [1, true], false)
RETURN DISTINCT n.id AS path
