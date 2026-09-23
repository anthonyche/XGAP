# Chapter 6 正式材料准备记录 — 2026-09-23

本轮边界：真实物化、独立题包、因子准入和可执行发布准备。没有启动三域全量，
没有为本轮准备调用模型。CPU/存储使用 Pioneer；后续模型仍用既有外部 API。
这是一份准备/准入报告，不是五方法质量或提速报告。

远程路径下文均相对于 `/home/hxc859/xgap-ch6-artifacts`；原失败不覆盖。

## 已核实材料

|域|逻辑核心|原始节点 / 边|数据库与答案准入|
|---|---|---|---|
|D1 SNB SF0.1|Person / knows|1,528 / 14,073|RDF 与原生均 8/8|
|D2 MovieLens 20M|User、Movie / rating|165,771 / 20,000,263|Neo4j 物化完成；大图查询 gate 尚未通过|
|D3 FinBench SF0.1|Account / transfer|20,409 / 79,909|RDF 与原生均 8/8|

时间视图会增加物理边/三元组，不能把视图副本计成原始独立事实。
这些是公开数据上声明的查询核心，不是三个官方 benchmark 的完整标准题集。

- D1 实际后端收据：`formal-core-v7/D1/admission/rdf/receipt.json`、
  `formal-core-v9/D1/admission/native/receipt.json`。
- D3：`formal-core-v9/D3/admission/{rdf,native}/receipt.json`。
- D2 原生完整物化：`formal-core-v5/D2/native/native/stores/receipt.json`。
  索引/导出成功不能替代查询 gate；8 题独立 SQL 参考在约 66.50 秒生成。

## 独立题包与实际因子

`formal-case-bank-v1/{D1,D3}/{rdf,native}/{development,test}/bundle.json` 已发布。
D1 test 为 RDF 32 / native 24，共 56；D3 为各 32，共 64。
所有 W1–W4、uniform/active-anchor 都按声明规则保留；模板族跨 split 隔离。
目前每模板/锚点分层只取 1 个锚点，这属于最小正式准备 bank，不等于已冻结最终样本量。
重复执行不能增加独立题目数；最终 CI 应按模板族聚类。

D1 `formal-core-v9/D1/factors` 的 28 个 N/u 实例通过后端/独立参考核对。
`formal-deployment-factors-v2/D1/receipt.json` 的 6 个部署均通过（每个两种锚点分层）：
2/4/8 源固定总事实；.25/1/4 倍实际改变输入图。不是改图例标签模拟因子。

## F6 当前可以说明什么

`formal-core-v9/D1/F6/measurement/receipt.json` 封存同一完整 Q 的四个等价计划，
各 3 次实测，12 次答案核对一致。终端成本中位数约 8,284–8,734 ms；
`sensitivity.json` 的 25 个位置覆盖五方法和五个 eta。
四个内部方法在该固定池子问题中共用选择器，当前 gap 全为 0；TS 无可比选择记录，null。
这支持“评分/等价池流程可运行”，不支持“XGAP 胜出”，也不是全查询空间最优证明。
该池保留原版本来源；后续物理邻域扩展不会追溯改写这个池或成本。

## D2 失败与修复边界

1. RDF 在 NFS 上读入约 3,400 万三元组后达到 3,600 秒上限。
2. 节点本地盘新尝试 `formal-core-v10/D2/rdf/stores/receipt.json` 约 420.50 秒读入
   1.13 亿三元组，随后超过 10 GiB 进程 RSS。8 GiB Java heap 不是总 RSS 上限。
   失败日志保留，不能称完成物化。下一版离线任务独立增加 RSS 预算，不改在线预算。
3. 统一规划准入 v1 的包装层误把 catalog 当 estimator，零后端调用即失败；已修复。
4. v2 的真实选中计划包含大范围 RATED 扫描，超过事务内存。
   `formal-unified-admission-v2/D2/native/receipt.json` 是实际计划失败，保留在记录中。
5. `7058d24` 为共享物理邻域增加必要锚点绑定与具有列来源证明的嵌套 join 绑定。
   保留最终约束与 join，拒绝无法证明的改写；固定深度/有界表示/一个最终计划不变。
   新替代计划仅在小图上做独立答案等价检查，未在当前正式题上竞跑选择。
   **真实修复版回放成功之前，不能宣布已解决 D2 查询瓶颈。**

恢复 OnDemand 登录后，准确版本 `7058d242844129fa7ab6cc277a6568fb52be982f`
已通过增量包哈希校验部署：3857752 为查询回放（24 GiB CPU allocation），
3857753 为 RDF 建库（64 GiB CPU allocation）。已观察到两者 RUNNING，
分别位于 compt294/compt267。新目录分别为 `formal-unified-admission-v3`、
`formal-core-v11/D2/rdf`；该状态不是完成回执。

## 全量启动前仍需完成

1. D2 RDF 封存及原生/RDF 大图查询准入，随后发布 D2 独立题包。
2. 以实际 prepared/profile/gate pins 发布五方法每题配置、manifest 和支持合同。
   W1 无可放松坐标；W4 hard scope 不能放松。TS 不接收私有 intent/controlled state。
3. 全部 21 图绑定真实执行单位或诚实的固定参考/不可评分状态。
   当前 probe registry 为空，E7 是未激活机制，不得伪造 probe 或 NP 差异。
4. 冻结最终 n、重复、API/token/墙钟/存储总预算，运行 release audit。
5. 按用户要求先运行一个数据集的有界结果批次，再讨论三域全量。

`prepare_ch6_execution_units.py` 已能在已准入 bundle 上按公开 finite family 发布
不同模板的正确配置与重复 manifest；仅准备，零模型/后端调用。
任务 3857763 正在为 D1/D3 当前 bank 准备三次重复的 NL 清单；不是启动这些请求，
也不是最终 n/全局预算已冻结。
本轮针对必要键改写、发布配置、loader 的小图/合同检查通过；没有追加全库回归或消融。
