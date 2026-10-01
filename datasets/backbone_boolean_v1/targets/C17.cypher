MATCH (n:Person)
WHERE NOT n:Ghost
RETURN DISTINCT n.id AS path
