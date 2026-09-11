MATCH (n:Person)
WHERE NOT coalesce(n.score IN [1, true], false) AND NOT coalesce(n.note = "open",false)
RETURN DISTINCT n.id AS path
