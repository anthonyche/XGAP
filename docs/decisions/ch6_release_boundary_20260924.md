# 2026-09-24：推进至全量可启动边界

用户授权冻结服务器配置、完成对应准入与 F6 成本核验，持续推进直到可确认全量
启动条件。此次授权包含必要的有界 CPU 准入和准备作业；不启动正式全量方法矩阵。
模型继续用既有外部 API，不申请 GPU。研究问题、21 图、五方法和支持口径不变。

执行顺序：

1. 只读盘点服务器实际文件及旧回执，先验证可复用证据，不按旧状态文字猜测。
2. 在独立 checkout 冻结引擎/补丁、准备数据、源存储位置和资源上限。新正式准入
   使用相同公共后端，明确区分已有诊断与新发布证据；不覆盖失败、盲目重提旧任务。
3. F6 检查同完整 Q、同计划池、同单位/计时范围、测量和服务运行身份，以及关闭
   证明。旧测量只有证据充分且配置相同时复用；不能以新标签补造身份。
4. 对三域 held-out、实际因子输入、源/规模部署、五方法支持合同、样本/重复与全局
   调用/token/墙钟/磁盘预算逐项核对，生成唯一冻结 release 与启动脚本。
5. 正式入口只做 dry-run。只有实际 release audit 全通过、缺失项为零，才报告
   可以开启全量。若有外部阻塞，记录具体缺失材料，不能把脚本就绪当全量就绪。

已知起点：`ff121ad` 已接好共同 runtime 合同，未在服务器冻结新合同。D2 原第 5
题及后续三题 EM=1；这组分次诊断不冒充整批准入。D1 F6 有既有四计划×三重复，
先检查原始证据决定是否可沿用，不为制造不同曲线修改四内部方法或 TS。

本轮只读盘点脚本 `collectrelease20260924.py` 已上传校验：
`8719ec8447907d53bfd5eff4cd47d0f122afa00078789bb81bca2b90c0f19798`。
收集正式材料 JSON 元数据与已有 F6 证据，单文件 8 MiB / 合计 96 MiB 上限；
排除数据库与源响应正文，不执行 backend/model，不提交 Slurm 作业。

已下载并校验元数据包（1,107,488 bytes）：
`1978c5223df126767885cd40882f7af3923a25ab0ac70666f4650d1ab74815f2`。
1231 个 JSON 文件覆盖实际材料；collector 在最后追加调度信息时遇到登录节点
Python 3.6 不接受 `text=True`，因此没有 inventory/调度附件。已写入的 tar 完整，
本地逐成员安全解包；不把 collector 的整个流程报告为成功。

实际 overall bank 为 D1 56、D2 56、D3 64 题，总计 176（不是初始每 W 200 的目标）。
D1/D3 使用 v1 test，D2 使用 v5 test。D2 test 仍指向旧 relative profile；与已修复
endpoint-degree profile 的差异只涉及 estimator、profile_id 和新增 offline provenance。
`rebind_ch6_profile.py` 仅允许这一变换，保留每个 case 的输入/私有用户/参考哈希，
拒绝任何源、语义或其他 offline 字段变化。局部测试 14 passed（含 runtime 合同）。

D2 `0ac3f60` CPU 准入包已落盘，32 RDF + 24 native held-out queries，每题一个
unified plan；无采集择优、无 LLM、无正式五方法调用。节点 compt311，8 CPU/24 GiB，
source RSS 4 GiB、worker RSS 3 GiB、worker 120 s、HTTP 60 s，服务副本 node-local，
离线启动 1800 s。RDF 冻结 Direct/lazy-v2；native 保留原 Neo4j/Fuseki。
包有输入核验、独立 checkout 和唯一 submission journal；浏览器上传控制反复退出，
截至本段尚未取得提交回执，不得推断已运行。

F6 当前旧四计划×三重复成本来自 evidence/NFS 存储，不能直接改标签当作 node-local
成本。新入口保留同一 Q、计划池、随机顺序和三重复，增加实际 engine/startup/storage
pins；服务关闭成功后才能冻结成本。`audit_ch6_cost_measurement.py` 零执行地复核
逐次 guard/worker、答案、成本、median、Z、误差扰动和关闭证据。发布检查要求 F6
与明确的 D1 RDF unit 具有相同 prepared、源资源、存储、runtime 与观测合同。旧记录保留。
四内部方法共享 terminal selector，允许重合；TS 仍不可评分，不优化基线结果。
