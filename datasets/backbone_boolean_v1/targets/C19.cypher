MATCH (n:Person)
WHERE NOT coalesce(n.flag IN [0,false],false)
RETURN DISTINCT n.id AS path
