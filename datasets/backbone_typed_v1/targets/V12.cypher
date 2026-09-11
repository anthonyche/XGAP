MATCH (n:Person) WHERE n.id = "missing" RETURN count(*) AS rows, count(n.amount) AS present, sum(n.amount) AS total, min(n.amount) AS low, max(n.amount) AS high
