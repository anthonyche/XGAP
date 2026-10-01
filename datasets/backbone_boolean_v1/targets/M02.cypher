MATCH (n:Person)
WHERE coalesce(n.score IN [1, true], false) OR coalesce(n.note = "open",false)
RETURN DISTINCT "https://xgap.test/toy/" + n.id AS person, n.score AS score, n.flag AS flag
