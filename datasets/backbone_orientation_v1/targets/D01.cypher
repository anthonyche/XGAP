MATCH (n0)<-[e1:KNOWS]-(n1)
WHERE n0.id = "b"
RETURN DISTINCT n0.id + "/" + e1.id + "/" + n1.id AS path
