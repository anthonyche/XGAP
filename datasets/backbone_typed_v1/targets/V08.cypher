MATCH (n:Person) WHERE n.score = 1 RETURN sum(n.amount) AS total, count(*) AS n
