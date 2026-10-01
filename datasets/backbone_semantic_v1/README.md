# Semantic DAG toy fixtures

These eight independently authored cases reuse the unchanged graph in
`../backbone_toy_v1`. S01–S07 cover seven semantic DAGs; S08 repeats S01 with
backend placement swapped. They exercise Match, Traverse (including input-bound
traversal), Filter, Project, Join, Union, Aggregate, OrderLimit and Align.

Expected rows, operator order and native source responsibilities are authored
before invoking the compiler. Source placement is separate from meaning.
Entity keys are full IRIs; path arrays retain the declared local ID encoding.
S02 checks ordered output; S06 is an explicitly synthetic alignment operation.
All graph facts and the original eighteen path-query gold chains are unchanged.
