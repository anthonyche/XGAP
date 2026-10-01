MATCH (n:Person)
WHERE coalesce(n.score IN [1, true], false) OR coalesce(n.note = "open",false)
RETURN DISTINCT n.id AS path
