# XGAP Current Roadmap

2026-09-15。当前工作时段和研究约束见[Goal](goal.md)。总体Goal未完成。

## 已通的有界骨架

- P-S1：finite-depth AND/OR strong policy、可行计划保留、EXACT/PERFORMANCE终止条件。
- P-S2：冻结catalog/可选LLM/按需绑定回答；同请求live模型→strong→真实Neo4j/Fuseki。
- P-S3：逐跳候选、完整读取共享、必要过滤、准备与预算优化；有tiny真实证据，未证明
  总体速度优势。冻结普通profile/record、共同真实worker与独立study接线均已实现。

具体测试/原始记录见[当前状态](status.md)，不重跑已成功门来增加计数。

## 剩余的研究发布顺序

1. 按[18图契约审计](research_contract_audit_20260915.md)明确主输入范围、可用信息与
   authority、两模式实际差别。当前沿用可信部分绑定结构；开放NL结构保证需独立契约。
   完整可信结构子轨已补入口、在线schema路由与模式开发配置，正接既有FinBench划分；
   它用于物理规划比较，不代替部分绑定下的信息获取实验。
2. 在开发条件下冻结论文profile/工具顺序与成本来源、估计器、PERFORMANCE改进预算。
   不用评价输出调参，不人为制造高澄清成本，不把unknown当0。
3. 发布具体逐题输入/参考/配置和外部共同前端。复用已实现study、共同guard、observer、
   score与journal，只检验新接线风险和必要vertical slice，保留失败replay。
4. 依已批准优先级执行真实FinBench native与同事实RDF FedUP/FedX，再bounded FedShop。
   主效率/质量/规模结果在前，消融在后；同图对照必须有相同事实与可比较的信息条件。
5. 用户推进d之后再接入其正式误差契约。无epsilon主张的评价不因此自动停止。
   GrailQA/KBQA-R1仍等待完整KB与作者artifact，不作为前两轨开发前提。

## 不属于下一轮默认任务

不继续建设无限语义/通用开源产品；不反复构建GrailQA catalog；不重提未知远端作业；
不优化baseline答案；不重跑旧成功门或改估计分数强迫新策略胜出。

[此前路线逐字快照](roadmap_history_20260915.md)保留全部历史，其旧调度/“下一步”不生效。
