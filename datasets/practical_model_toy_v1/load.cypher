CREATE (a:Person {id: "a", name: "Alice", age: 30}),
(b:Person {id: "b", name: "Bob", age: 22}),
(c:Person {id: "c", name: "Cara", age: 40}),
(d:Person {id: "d", name: "Dan", age: 19}),
(z:Person {id: "z", name: "Zoe", age: 50})
CREATE (a)-[:KNOWS {id: "e1"}]->(b),
(b)-[:KNOWS {id: "e2"}]->(c),
(c)-[:KNOWS {id: "e3"}]->(a),
(a)-[:KNOWS {id: "e4"}]->(c),
(c)-[:KNOWS {id: "e5"}]->(d),
(d)-[:KNOWS {id: "e6"}]->(d),
(a)-[:KNOWS {id: "e7"}]->(b),
(b)-[:KNOWS {id: "e8"}]->(d),
(a)-[:FOLLOWS {id: "e9"}]->(z);
