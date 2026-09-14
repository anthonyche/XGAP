# P-S2：信息工具与真实双后端小图开发门

2026-09-14，接续 P-S1 `d544aca`。用户已授权持续迭代，应用 Goal 已用新方案创建，
工具确认 active。总体系统/论文目标未完成。本报告是 research prototype 开发证据。

## 已实现与准入范围

- 冻结 catalog 作为显式信息动作：只接受完整、无歧义且带权威标记的实体匹配。
  版本不符、歧义、空集、截断/未完成扫描均不产生伪验证。schema存在不等于用户意图。
- 可选模型动作复用现有 OpenAI-compatible 单请求、无 repair provider；冻结配置及
  实际 prompt hash；只返回有界非实体候选，不能自封权威。多个候选不会偷偷取第一项。
- `unavailable/error` 是声明的 AND 结果，必须有可行后续；缺少后续时诚实报告无plan。
  预先选择的另一个信息动作是显式分支后续，不是运行后新增的隐式 retry。
- 能力查询在搜索前读取已配置的源/版本/adapter/language；真实 compiler 仍检查每个
  operator 的能力证据。能力声明不意味着服务器在线，也不是语义权威。
- 实际模型、token、信息远程请求和耗时分别记录。缺失用量为未知；预算预留不冒充
  已测用量。catalog构建继续完全离线，运行时只读既有冻结artifact。

实现入口：[practical_tools.py](../../src/xgap/agent/practical_tools.py)、
[执行协调器](../../src/xgap/agent/practical_execution.py)、
[普通请求入口](../../src/xgap/agent/practical_question.py)。

## 验收结果

14项不同的新风险检查通过，另有3项受影响旧检查通过。新检查覆盖：catalog按需调用、
歧义分支、无权威后续时拒绝false strong、模型失败后用量保留、未知token、越界候选、
模型伪权威、版本与请求范围、真实provider代码的受控transport、prompt漂移、多个候选
和未完成扫描。不是重复跑全量回归；新增与修正后仅运行相关案例。

真实服务使用 Neo4j 5.26.30、Fuseki 5.6.0，加载原5节点8边toy。输入为可信模板NL：
查找 Alice knows 的人员，年龄至少30，返回人员和边。路径访问Neo4j，人员条件访问
Fuseki；部署使用同一冻结事实的两个逻辑source名称，原source hole仍实际应用到路径。

|观察项|本次记录|
|---|---|
|最终答案|Cara，边e4；与预先编写的1条gold完全一致|
|执行|1个最终联邦计划；Neo4j/Fuseki各1请求|
|信息动作|1次catalog获取；0次澄清、0模型调用|
|strong search|展开9状态；首次可行43.305ms，总搜索43.306ms|
|本次在线耗时|278.202ms，执行协调器224.736ms，catalog动作0.072ms|
|独立准备|服务启动7365.592ms，加载274.010ms，均单独记录|
|估计器|未提供；验证“未知估计仍可返回合法基础计划”|
|收尾|两服务均正常关闭，0自动retry、0候选试跑|

这是一条开发请求的一次记录，**不构成平均延迟、速度提升或成本最优性结论**。
执行器的bytes_moved是内部指标，本次没有独立HTTP字节测量，不能解释为零网络流量。

## 失败与边界

首次本地测试9失败/3通过，原因是新adapter的默认空question不满足已有request契约；
改为显式必填，9项新检查通过。真实门a1在服务启动前发现测试部署绕开了必需source
hole，编译器以“required resolution未用于可执行含义”拒绝；0服务、0源查询。
修正部署使source绑定仍进入路径后，a2才执行唯一最终查询；a1失败原样保留。
OpenAI适配另发现输入候选上限与输出上限共用契约，不能把输出cap=1用于多输入候选；
保持既有有界契约，多个输出走unavailable，相关修正与新增风险检查已通过。

新LLM动作测试使用真实provider代码与受控transport，**尚未调用live endpoint**。
实际双后端检查为模板NL与冻结catalog，尚非自由NL→可信结构的精度证明。
澄清后续是独立绑定文件，仅含语义选择，不含结果行或目标查询；其声明结果为Alice/Bob。
强计划保证仅针对声明结果，未建模文件/服务器故障会终止，不保证外部服务永不失败。
未发明discrepancy、epsilon保证、启发式近似比或全局最优证明。

## 可复核证据与下一步

[版本和检查账本](../../experiments/artifacts/practical_information_native_20260914.json)；
[真实检查脚本](../../scripts/check_practical_strong_native.py)；
[最终receipt](/Users/anthonyche/xgap-data/practical-strong-native-20260914-a2/receipt.json)；
[封存结果](/Users/anthonyche/xgap-data/practical-strong-native-20260914-a2/result.json)；
[a1失败](/Users/anthonyche/xgap-data/practical-strong-native-20260914-a1/receipt.json)。
每个源请求的intent和response均独立封存；查询执行前封存输入，结果封存后才评分。

进入P-S3：增加保持语义的后续跳绑定传播候选，先测极小多跳图上的答案与源行数，
再做必要真实边界。两模式共用该执行优化。旧44个FinBench结果和原分母不变，未进行
新baseline/ablation/大数据运行，也未优化baseline方法。
