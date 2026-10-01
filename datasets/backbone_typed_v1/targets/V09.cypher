MATCH (a:Person),(b:Person) WHERE a.score = b.score RETURN "https://xgap.test/toy/" + a.id AS left, "https://xgap.test/toy/" + b.id AS right
