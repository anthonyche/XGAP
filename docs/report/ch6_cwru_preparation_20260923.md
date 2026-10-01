# CWRU CPU 迁移与正式实验准备进度

本轮目的：利用 CWRU 存储和 CPU，继续调用既有 Qwen API；准备到正式全量发布边界。
未申请 GPU，未发布全量实验。当前状态不能简写为“所有正式实验已经 ready”。

## 已完成的可审阅产物

- [21 图五方法合同](../ch6_formal_execution_20260923.md)：390 个设计格、60 个整体 workload 格。
  XGAP/NP/SH/GR/TS 均保留；unsupported/null、固定参考、支持率与同子集配对口径已明确。
- 21 图绘图器已完成输出检查。数值图中未运行的正式格仍为 pending；C1 只取实际动作，
  T1 从封存轨迹导出，不把假设搜索或缺失 TS 轨迹伪装成已执行动作。
- cohort 汇总核对 request、question、source/deployment、method 和重复身份；保留失败分母、
  缺失重复与 study censoring，按模板族计算 CI。3 项针对性汇总测试通过，历史 5 方法 tiny
  记录复算一致，未增加模型调用。Linux 传输相关 6 项测试通过。
- 本地结果矩阵工作簿已填入绘图计划、正式待测格、支持与覆盖表、开发验收和口径来源。
  已有 tiny 结果单列，未填入正式结果格。

## CWRU 当前证据

- 独立实验目录读写已验证，已有 FinBench SF0.1 官方固定 archive 哈希一致。
- CPU 作业 3856445：统一入口、存储和现有 Qwen API 通过。一次生成返回 OK，
  653.87 ms、17 input / 2 output tokens；这是连通性检查，不是性能结论。
- 原版作者依赖已安装。3856623 的 Linux bootstrap 成功，复用阶段耗时 60.35 s。
  Mac 本地文件 URI、自检缺配置、环境目录别名检查等迁移失败已保留并定位；修复仅涉及环境/路径。
- 作业 3856638 的 Linux tiny RDF/FedX/Redis/lookup 验收成功：跨源结果 4 行，与独立参考完全一致；
  6 次 source 请求、0 失败、0 模型调用，所有自建服务关闭。Slurm 总状态 FAILED 是同作业数据下载
  阶段的 MD5 文本格式解析错误，不能改写成整作业成功。服务回执 SHA-256：
  `8f470e779c7b91bded8c1cb496497de8d980e40f8c74c0a36b0137f2241af515`。
- 官方 MovieLens 20M 的 BSD 格式 MD5 已核实并修正解析。仅数据下载作业 3856649 已提交；
  不重复已成功的数据库/基线验收，旧失败完整保留。

详细安装、路径、数据和作业证据见[CPU 迁移记录](../decisions/ch6_cwru_cpu_20260923.md)。

## 距离全量发布还差什么

|项目|当前边界|
|---|---|
|D1/D2 正式 snapshot 与物化|开发小图不能冒充正式规模；MovieLens 源 archive 冻结也不等于图装载完成|
|三域独立测试题|按模板族隔离 development/pilot/test；uniform 与 active-anchor 分开报告|
|N/u/source/scale 实际输入|容量单测已做，正式因子输入的合法性与源快照还需逐份准入|
|F6 固定等价计划池|同 Q、同单位的 offline 成本与估计误差尚未冻结；TS 不可评分时保留 null|
|混合支持合同/预算|实际单源/RDF/异构题目、支持依据、重复数和总 API/token/墙钟预算须发布前冻结|
|最终 release|必须通过实际输入与证据齐全的 audit；空表和脚本可运行都不能代替它|

当前结论是：CWRU CPU + 外部 API 的路线已验证可用，依赖可移植；正式评估资产准备仍在进行。
