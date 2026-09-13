# 冻结键上界与 one-shot 选择接通 — 2026-09-13

本轮实现630d802/e9acb6b，将离线源信息、冻结估计和实际绑定限额接通。
统计来自完整源事实；无需每道题先跑多种计划。普通入口只执行一个估计选中的计划。
这项工程门已经验收；随后真实新组7中两模式均完成全链路，得到正确空答案。

## 已实现与范围

新增可选的 source/snapshot/namespace/label/property 冻结统计契约。统计的是所有
字符串值中最大的匹配记录数，重复记录只会使上界更保守。对已证明必要的锚点
UNION求和，收紧实际max_bindings；估计器读取同一限额。未覆盖属性、非字符串或
缺统计保留原界；错误hash、快照或命名空间被拒绝。不从字段名推断唯一性。

没有改查询语义、模型权重、特征维度、模型提示、baseline算法/配置或原数据。
候选域仍为D*(1+2J+A)、A<=1；新增查找传播O(D*n*S)，仍是多项式。
选择仍是声明域中估计值最小的计划；真实耗时最优和全局近似比未得到证明。
[算法及条件](../decisions/equality_key_bounds_v1.md)。

共16个新风险案例通过：统计10个、源文件适配6个。首次测试暴露导出器误认为
backend profile必填；修复后实际冻结配置通过。只重跑该失败和受改动影响的检查，
没有 broad regression。覆盖重复值、两提供方、空上界、缺属性、类型差异、错误
hash/快照/命名空间、原资源限额及真实冻结模型。

## 实际 tiny 普通入口

复用已冻结8实体/16关系的Neo4j+Fuseki；在独立gold interpretation后进入正式
one-shot选择入口。源文件离线导出/统计约38.8ms，单独计作一次性准备成本。
普通链由模型选择coordinator，最终计划1个，独立预期4行全部exact；源14调用、
18606响应字节，planning118.950ms、execution1270.915ms、封存前online1412.236ms。
所有自有源进程组退出、observer停止，保留结果，清理了可重建的服务副本。

这是deterministic planning链的真实边界验证，模型调用0；Interpretation没有新改动。
该小图上的绑定上界为2，fanout估计297.949→226.711ms，coordinator仍28.933ms。
没有强制选择fanout，没有额外执行替代计划；本例不证明某种计划实际更快。

## 完整真实源的离线准备与排序诊断

在已封存的实际RDF graph/control文件上各扫描55604实体，完整匹配源文件hash、
源快照、类型数量和业务ID覆盖；所有类型的id最大重复度均为1。两源求和上界2。
这里只覆盖业务id，其余属性继续保守处理。完整准备9.206秒，两个源导出各4.14MB，
统计文件合计约2.6KB；没有数据库/LLM/训练/catalog/summary调用，没有读取评价答案。
一次性源扫描可跨后续查询摊销，运行时仅加载小型冻结统计。

复用已曝光组6保存的解释，**保持其原始operator_sources**，比较同一程序的新旧
统计配置。9个候选、构造上界18：coordinator估计保持834.612ms；fanout由
12842.692降至777.969ms，原冻结模型现在自行选择fanout。三个首边请求的bind-record
单位从30000降至6，来自完整源最大重复度，而非把本题观测的1个键写入参数。
这是静态预测诊断，没有重新执行旧问题、修改旧分数或拟合权重，不是实测提速。

更早一次诊断误用了schema_source_routing重新分配三处ID读，得到533.257/467.205ms；
该诊断已另存并明确标记，不用它代表原始trace。上述834.612/777.969才是原路由的
配对比较。原始记录与两套诊断均保留，未覆盖。

## 当前实验衔接

新冻结配置及store/FedUP summary关联已发布，零重新装载/summary构建。新journal
finbench-rdf-nl-campaign-20260913-equality-v1继承旧28个结果，保持原48题、方法顺序、
预算和失败分母；下一项是从未执行的组7。旧journal作为证据，不再从那里分发。
本轮只允许这一组四方法各一次，以验证真实NL在原内存预算内的行为；不重复旧失败。
Native fixed下一20，RDF fixed下一5；native NL尚未启动。

## 证据

[验收与hash索引](../../experiments/artifacts/equality_key_bounds_20260913.json)、
[真实tiny回执](/Users/anthonyche/xgap-data/equality-bounds-native-20260913-v1/receipt.json)、
[完整源准备](/Users/anthonyche/xgap-data/finbench-equality-bounds-20260913-v1/receipt.json)、
[原路由排序诊断](/Users/anthonyche/xgap-data/finbench-equality-bounds-20260913-v1/original-routing-ranking.json)。

## 真实新组7：两个模式均完整完成

四方法沿原次序各首次运行一次，合计4次模型调用、12296输入/2015输出token。
该题独立gold为空；原旧28个结果未改变，不能把本组与旧版本合并宣称总体成功率。

| 方法 | 结果 | 完整在线耗时 | 源调用 | 源响应字节 | 方法峰值RSS |
| --- | --- | ---: | ---: | ---: | ---: |
| XGAP精度 | 正确空答案，EM1 | 80.876s | 14 | 182844047 | 2111209472 |
| XGAP性能 | 正确空答案，EM1 | 84.423s | 14 | 182844047 | 1653735424 |
| FedUP | 原生执行失败，EM0 | 7.555s | 0 | 0 | 516718592 |
| FedX | 共同响应预算中断，EM0 | 12.935s | 1501 | 556318163 | 395968512 |

两模式都选择placement-0/anchor_fanout_bind，上界2，最终执行各1次。
其core planning为60.390/59.367ms，core execution为67.020/67.226s。
模型估计777.969ms不是校准后的绝对执行时间，不能把估计数字当成实测耗时。
实际online还包含解释、I/O/捕获和共同外层开销，表中报告完整时间。
本题两种模式选择同一策略，不能据此声称精度/性能Pareto优势。

这是“真实NL—冻结估计选择—源端绑定—联邦执行—封存—独立评分”实际接通的证据。
它尚不证明非空NL正确率、整体效率、scalability或优于SOTA；尤其不能把失败方法的
较短终止时间解释为更快回答，或把不同题的前后耗时解释为同题提速。
Baseline原生代码与配置完全未改，失败和中断原样纳入分母。

完整trace为603911890/603911887字节；精度模式峰值接近原2147483648字节方法预算。
代码核查确认scheduler当前保留所有中间rows，而结果序列化再次物化每个节点rows。
这提供了明确的下一工程方向，但尚未证明它占全部执行时间的比例。下一步按[独立tiny门](../decisions/one_shot_trace_retention_next.md)，先在小图
上验证仅one-shot启用的中间数据生命周期/紧凑trace，保留最终答案、节点计数、
实际源请求及重放证据；不再通过重复大题定位问题。

控制器71240已exit0，3次session retirement均确认全部自有进程组退出和observer停止。
该chunk213.695s，package采样峰值3.888GB，最终空闲11.264GB，高于6GiB reserve。
当前NL frontier为新journal下一group8，旧journal不再分发；native/RDF固定语义frontier
仍分别20/5。Goal仍active，整体系统/正式论文评价尚未完成。

[本组逐题与资源审计](../../experiments/artifacts/equality_campaign_group7_20260913.json)、
[原始审计](/Users/anthonyche/xgap-data/finbench-rdf-nl-campaign-20260913-equality-v1/group7-audit.json)。

## 本轮结束后的用户安排

用户要求本轮结束即暂停。全部实验/服务已终态，工程与实验停止，
2026-09-14 10:00北京时间恢复。整体Goal仍未完成；下一步为小图中间结果生命周期/
紧凑trace门，NL journal下一group8，不重试本轮或此前问题。
