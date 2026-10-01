# 当前工作入口与历史证据分开

Goal/status/roadmap/decisions累计13,600行，包含许多已被后续版本覆盖的“当前任务”、
“下一步”和暂停安排。这会使自动续跑重复读取过期任务，增加上下文成本并造成误执行。

本轮将四份原文件逐字保存为同目录的`*_history_20260915.md`，其SHA-256逐份核验
与原文件一致；同目录保持原相对链接位置。当前四个入口整理为181行，指向实际技术
契约、原始报告、当前差距和用户时段。未删除历史技术规定、旧失败、实验结果或分母。

AGENTS改为从当前决策索引读取相关专题，保留所有层次/语义/研究/基线/权限不变量。
未来更新当前状态并链接独立report，不再重复堆叠历史“下一步”。接触旧API/语义时仍
需定位对应历史条目；历史快照作为溯源，不是新执行指令。

[逐字历史与入口校验](../../experiments/artifacts/harness_document_history_20260915.json)：
四份历史hash一致，当前索引链接全部存在，diff格式检查通过。没有程序行为变更，
不运行软件回归、模型、数据库或实验。181行是本文封存时的入口长度，可随当前状态
简要更新；不把行数下降换算成未经实测的token或运行速度收益。

MaterialPassport: documentation/harness organization; original history preserved;
zero new experiment or software-result claim.
