MATCH (l:Person {id:"a"}), (r:Person {id:"b"}) WHERE l.id = CASE r.id WHEN "b" THEN "a" ELSE r.id END RETURN "https://xgap.test/toy/" + l.id AS person
