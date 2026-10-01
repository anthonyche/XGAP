MATCH (n:Person)
WHERE NOT coalesce(n.score IN [1, true], false)
RETURN DISTINCT "https://xgap.test/toy/" + n.id AS person, n.score AS score, n.flag AS flag
