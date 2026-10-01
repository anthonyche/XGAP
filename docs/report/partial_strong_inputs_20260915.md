# FinBench 部分绑定输入与配置候选

## Material Passport

2026-09-15；实现`70a5799`，批次内依赖复用`7daa7a0`。本轮交付真实输入元数据与
离线开发规划证据，未执行SF0.1查询、未调用模型、未读取query答案、未启动正式评价。
输入是作者派生的可信关系槽结构，不能称为官方FinBench NL任务或自然歧义样本。

## 已交付

原生与同事实RDF各120题，保留原question ID、题文、曝光、家族、24/48/48划分和
独立参考答案指针。只替换家族预先指定的关系标签：直接转账控制家族的ownership、
时间路径家族的transfer、风险聚合家族的sign-in。重复关系使用同一个predicate槽。
日期、ID、方向、节点类型、过滤、聚合、输出、排序、limit保持；权威绑定后逐算子
精确还原原程序。两个表示的题目身份一致，968个生成元数据pin已核验。

两个模式获得相同候选集合、模型/权威工具与初始信息；初始绑定和预测都为空。
模型只能提议，EXACT仍需权威验证。PERFORMANCE可采用明确授权的关系预测。
权威工具按需读取声明的semantic annotation，仅含绑定，不是查询结果；该额外信息
在输入条件中公开，计实际访问成本，不虚构人工等待。配置是开发候选，尚非论文默认值。

源分配在这个子轨是显式提供的语义输入，两模式共享，不能据此评价source discovery。
原生配置接两个XGAP方法，RDF配置接六个显式方法/模式。不同信息条件与旧完整输入
在线schema routing轨分开，不把费用或分母混在一起。已知FedUP生成形式不支持仍保留。

发布期间发现反复admit相同catalog的离线开销。原生首版120次admission用174.13s；
随后复用严格相同的冻结依赖，RDF版1次admission用2.42s，每题仍验证模板、源分配和
权威恢复。原始首版保留，没有重新发布它来制造更好的计时。这是不同代码版本的
一次性metadata成本，不是Neo4j/Fuseki查询速度对比；两者均0 catalog build/fit。

## 开发计划可得性

按manifest顺序选每个家族的第一个development题；两种表示、两个模式，共12次
离线规划。网络连接被禁止，`execute=False`；0模型、0权威工具调用、0源调用。
12/12均生成strong策略，不是12题答案正确，也不是完整评价分母。

|表示/模式|直接转账控制 ms|时间路径控制 ms|风险聚合排序 ms|
|---|---:|---:|---:|
|原生 EXACT|254.35|298.47|246.30|
|原生 PERFORMANCE|164.04|203.39|165.97|
|RDF EXACT|138.31|139.07|109.01|
|RDF PERFORMANCE|67.32|87.92|69.00|

表中仅search计时；profile admission另存，不含模型或实际查询。每条件一次、非随机
重复，不能用它声明总体提速或准确性收益。PERFORMANCE以基础可行策略为主的候选
配置减少了这里的规划工作，但其端到端执行代价尚未测量。

策略内容给出下一步的具体问题：六个EXACT策略都先选`llm:relation`，其每个声明
结果（3个候选、error、unavailable）随后都调用同一`clarification:relation`。
当前信息费用为null，冻结启发式顺序保留了这个冗余前缀。下一步检查能否利用EXACT
验证状态的不变性安全剪掉该动作；这不是调整baseline顺序或伪造信息价格。

## 定向检查与证据

10个新增case及1个受影响closed-intake检查最终通过；没有全套回归。首次1 failed/
7 passed抓到publisher对共享嵌套参数的原地修改，已改为复制后转换，恢复检查通过。
新增RDF分支首次因测试fixture把一个backend重复配给两个source失败，修正fixture后
通过；运行时资源契约未放宽。依赖复用另检查source范围及批次内版本漂移拒绝。

检查入口：`tests/test_partial_strong_inputs.py`及受影响的closed-intake pin case。
实际发布使用`publish_partial_strong_inputs.py`，两份完整manifest及原输入pin均在
[证据文件](../../experiments/artifacts/partial_strong_inputs_20260915.json)中；SHA
`e4c4192fa407eb1ea13e41513cc99e72e0ae5f3563989030d78c6f33f0686e56`。
离线规划receipt SHA
`94964714d3e61d2d948a0d53c571dd7797d3c1d59a2709bc47a338c2ca61bcd7`，保存完整策略、
源码提交和实际driver hash。无活动native服务、无大数据集执行、无自动重试。

## 下一步

输入候选和共同前端已有可执行实现。剩余是消除上面的EXACT无效信息路径、明确实际
信息估计/排序依据、验证最终模式配置，并完成论文release与共同支持范围讨论。
核心RQ仍是同输入权限下的信息/物理联合规划成本与正确完成；先形成主结果，再做
正式消融和规模实验，不用这些开发规划数字替代论文实验。
