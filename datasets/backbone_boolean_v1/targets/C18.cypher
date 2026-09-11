MATCH (n:Person)
WHERE coalesce(n.flag IN [0,false],false)
RETURN DISTINCT n.id AS path
