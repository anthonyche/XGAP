# 新strong逐题配置与单组续跑接线已实现

实现`82dd2ad`，[范围与计量](../decisions/practical_study_v1.md)。新入口可将每题的
request/profile/评分reference冻结为独立study，并经已有共同trial和journal执行最多
一组。旧48组schedule、旧方法列表、外部baseline及其结果全部保持。

6项新定向检查首次通过（0.41s），0网络/模型/真实源调用：冻结两组共享profile并交替
模式顺序；只运行当前组；续跑跳过已封存及已写intent但状态不明的格子；方法失败后
停止当前会话余下格子；评分失败保留而不重跑；拒绝重复题ID、改变模式配置或绕过
observer的部署地址。测试用受控trial结果验证接线，不作为两模式真实答案/耗时证据。

运行输入与评分reference分开，准备/部署回调及方法参数都不拿reference pin；期待
答案仅在方法结果封存之后交评分器。源/模式/依赖配置固定，只允许部署URL和明确的
离线部署记录变化。每个源必须走拥有者提供的observer。caller持有真实服务句柄并
负责启动/关闭；没有按PID接管外部服务。

部署检查和调度时间另记在共同方法在线时间外层，不伪装成免费每题工作；服务启动
单列。未知状态从不自动重试，后续可用新serving会话继续未启动的格子。旧campaign
CLI会拒绝新deployment类型，避免误走旧NL/固定语义路径。

这个批次接口已实现并有局部接线证据，真实执行仍复用先前已通过的common worker；
尚未新增一个经过此study包装的真实双模式批次。不重复native门来制造验证数量。
正式部分绑定population、两模式参数、外部共同前端与release manifest仍未发布。
本轮不生成新题、不看评价输出调参、不启动正式大图或消融。

检查命令：`PYTHONPATH=src:tests:scripts /tmp/xgap-directed-tests.qU2YfW/venv/bin/python
-m pytest -q tests/test_practical_study.py`，exit0。[证据索引](../../experiments/artifacts/practical_study_20260915.json)。
[更新后的完成范围与18图草案](../research_contract_audit_20260915.md)。02:00收尾、10:00恢复。

MaterialPassport: frozen input and controlled dispatch evidence; no new native
study, external-method modification, paper population or statistical result.
