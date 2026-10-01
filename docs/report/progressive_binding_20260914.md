# P-S3 本地门：逐跳绑定已实现，真实性能结论待验证

2026-09-14，接续P-S2 `3cdae2b`。Goal active，用户授权持续迭代。
新候选只在当前strong profile的可选物理改进中默认启用，legacy/baseline domain保持原样。
[算法与多项式界限](../decisions/progressive_binding_v1.md)。

## 实现和局部证据

已有fanout仅约束各路径的第一跳。新`progressive_entity_bind`候选从可用fanout或
coordinator开始，按语义DAG深度与稳定ID顺序逐个考虑Join，将实际前缀的身份绑定传给
后续Match。每个Join最多接受一处改写，不组合枚举；所有原Join/Filter/Aggregate保留。
相对于旧domain每placement最多增加一个候选，界限为`1+2J+A+G`，A/G各0或1。
共享输出、非身份键、已绑定目标、环和不支持的native形状被记录并跳过。

6项新检查与1项受影响的未知估计兜底检查通过。首轮4通过/1失败是测试误把不同
计划节点的相同查询文本当重试；改用artifact身份追踪后，overflow与empty分支通过。
系统未出现额外重试，也未执行另一候选来修复失败。

|组件观察|仅第一跳fanout|逐跳绑定|
|---|---:|---:|
|独立gold行数|6，完全一致|6，完全一致|
|有绑定的关系请求|3|6|
|后三跳返回行|24|19|
|逻辑交换字节|7286|6401|
|源请求数|8|8|

上表是独立5节点/8边小图上的两次预定组件执行，**不是在线试跑选计划，不是正式消融**。
原图含平行边及自环。另一个两跳bag计数请求不依赖fanout，正确计数为7：两条a→b
接b→c贡献2，a→c→d贡献1，a→a再接a的四条出边贡献4，绑定去重未改变答案重数。
空起点只读两个属性源，6个关系请求全部跳过；中间绑定超限明确失败，不截断/重试。
共享目标作为独立答案root时不被限制；组合依赖图保持无环。

## 估计器可运行，尚无选优或提速结论

另读取既有、已冻结的native tiny profile，零数据/模型请求、零fit：新domain实际10个
候选，预构建界限19。冻结模型能评分逐跳候选（8个bind节点），估计717.281ms，仍选
coordinator（28.933ms）。该profile与上表的独立RDF小图不同，不能将估计差当实测差。
没有改权重、源统计或排名来让新候选胜出。

这说明新候选已进入现有估计路径，且完整答案保持下的源读取下降机制在toy有效。
不能据此说明估计器错误、新策略整体更快，或performance模式已获得足够优势。
绑定引入串行依赖与参数处理，减少字节未必减少延迟。真实组件门及实际排序验证仍待做。

## 证据和接续

[版本/门禁账本](../../experiments/artifacts/progressive_binding_20260914.json)、
[逐跳实现](../../src/xgap/runtime/progressive_binding.py)、
[新风险测试](../../tests/test_progressive_binding.py)、
[冻结估计记录](/Users/anthonyche/xgap-data/progressive-binding-offline-20260914/estimator.json)。

下一步仅执行新候选的必要真实Neo4j/Fuseki tiny门并记录完整原始响应，随后基于实际
结果决定估计器/执行成本的下一处改进。不启动大图，不调整baseline，不宣称全局最优、
启发式实际成本近似比或用户尚未定义的语义偏差界。P-S3整体仍在进行。
