MATCH (n:Person)
WHERE coalesce(n.flag IN [0,false],false)
RETURN DISTINCT "https://xgap.test/toy/" + n.id AS person, n.score AS score, n.flag AS flag
