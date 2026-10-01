MATCH (n:Person)
WHERE n.score IS NOT NULL AND NOT coalesce(n.score IN [1, true], false)
RETURN DISTINCT n.id AS path
