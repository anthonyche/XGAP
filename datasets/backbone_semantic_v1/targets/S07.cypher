MATCH (l:Person {id:"a"}), (r:Person {id:"a"}) RETURN l.age AS left_age, r.age AS right_age
