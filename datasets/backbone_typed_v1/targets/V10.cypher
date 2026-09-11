MATCH (n:Person) RETURN DISTINCT CASE WHEN n.score IS :: INTEGER NOT NULL OR n.score IS :: FLOAT NOT NULL THEN toInteger(n.score) ELSE n.score END AS score
