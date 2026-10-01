MATCH (n:Person) RETURN count(*) AS rows, count(n.vacant) AS present, sum(n.vacant) AS total, min(n.vacant) AS low, max(n.vacant) AS high
