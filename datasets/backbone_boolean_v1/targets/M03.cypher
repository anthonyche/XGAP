MATCH (n:Person)
WHERE CASE WHEN n.score IS :: INTEGER NOT NULL OR n.score IS :: FLOAT NOT NULL THEN n.score > 0 ELSE false END
RETURN DISTINCT "https://xgap.test/toy/" + n.id AS person, n.score AS score, n.flag AS flag
