# M12-A Experiment Artifact Contract + Dataset Bundle

Freeze the experiment-facing semantics and implement versioned DatasetBundle,
ModelBundle, ExperimentSpec, semantic-deviation, GP protocol, baseline,
ablation, metric, execution, manifest, hashing, and run-layout contracts.

Add a controlled financial-risk development bundle, mock M10 ModelBundle, and
offline runner proving that conforming artifacts can drive the existing M11
planner without dataset-specific planner changes.

Do not implement live LLMs, production ontology reasoning/alignment, KGQA
loaders/evaluation, real server calibration, within-task GP updates,
executable baseline/ablation matrices, large-scale orchestration, or final
paper results.

Acceptance requires focused tests, full pytest, a controlled development run,
run-tree verification, acceptance-script success, and current-state docs.
