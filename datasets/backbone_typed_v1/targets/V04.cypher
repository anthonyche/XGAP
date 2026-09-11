MATCH (p:Person) WITH CASE WHEN p.score IS :: INTEGER NOT NULL OR p.score IS :: FLOAT NOT NULL THEN toInteger(p.score) ELSE p.score END AS score RETURN score, count(*) AS n
