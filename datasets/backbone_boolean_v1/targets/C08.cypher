MATCH (n:Person)
WHERE NOT n:Person OR coalesce(n.score = "1",false)
RETURN DISTINCT n.id AS path
