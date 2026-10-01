CREATE
(a:Person {id: "a", name: "Alice", age: 30, score: 1, note: "open", flag: true, floor: -9223372036854775808}),
(b:Person {id: "b", name: "Bob", age: 22, score: 1.0, note: "closed", flag: false}),
(c:Person {id: "c", name: "Cara", age: 40, score: true, flag: 1}),
(d:Person {id: "d", name: "Dan", age: 19, score: "1", note: "open", flag: 0}),
(z:Person {id: "z", name: "Zoe", age: 50}),
(a)-[:KNOWS {id: "e1", weight: 1}]->(b),
(b)-[:KNOWS {id: "e2", weight: true}]->(c),
(c)-[:KNOWS {id: "e3", weight: "1"}]->(a),
(a)-[:KNOWS {id: "e4"}]->(c),
(c)-[:KNOWS {id: "e5", weight: 0}]->(d),
(d)-[:KNOWS {id: "e6"}]->(d),
(a)-[:KNOWS {id: "e7", weight: 1.0}]->(b),
(b)-[:KNOWS {id: "e8", weight: false}]->(d)
