MATCH (n:Person) RETURN count(*) AS people, count(n.score) AS present, count(DISTINCT n.score) AS unique
