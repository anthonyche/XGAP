MATCH p=(n:Person)-[:KNOWS*1..3]->(m:Person)
WHERE n.id = "a"
WITH n, m, collect(p) AS paths, min(length(p)) AS best
UNWIND paths AS p
WITH p, best WHERE length(p) = best AND (last(nodes(p)).id IN ["c","z"])
RETURN DISTINCT reduce(s = nodes(p)[0].id, i IN range(0,length(p)-1) | s + "/" + relationships(p)[i].id + "/" + nodes(p)[i+1].id) AS path
