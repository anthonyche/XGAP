# 修复后48题：3890655 已提交

2026-09-27。用户终端回执确认：完整独立 bundle 成功接收，精确 checkout 为
`f40dfa9024f1473a90e6f340fb787f90ca204c46`；六份 manifest 发布；
`audit_passed=true, unique_cases=48, method_requests=216`；隐藏密钥输入后打印
`SUBMISSION 3890655`。这关闭此前 Git alternates 交付故障。

证据级别为用户提供的终端回执。服务器发布过程检查已通过；下面 manifest 原文件
尚未回收核验。本次浏览器 getState 20秒超时，未获新的服务器状态。已请求只读
sacct 与日志；没有取消、重提或修改服务器对象。

## 执行范围与句柄

- 每域16题，W1–W4各4题；native/RDF、uniform/active-anchor 保持原冻结分层。
- XGAP/NP/SH/GR各48请求，TS 24个RDF请求；24个TS原生位置不支持。
- D1→D3→D2，一次重复。8CPU/24GiB、无固定节点/无GPU，沿用外部LLM API。
- staging：`/home/hxc859/xgap-ch6-artifacts/small48-fixed-f40dfa9-independent-v1`。
- output：`/home/hxc859/xgap-ch6-artifacts/small48-fixed-results-f40dfa9-independent-v1`。
- 日志：staging 下 `small48-3890655.out`。
- 预期归档：`/home/hxc859/xgap-small48-fixed-3890655.tar.gz`。
- 调度状态、实际节点、计算节点认证及调用用量目前未知。6小时是冻结研究时限，
  6:15是Slurm申请上限，不是完成时间预估。

## 服务器回传 manifest

路径均为 staging 下 `published/<cohort>/unit/manifest.json`。

| Cohort | Bytes | SHA-256 |
|---|---:|---|
| D1-native | 42738 | `166d27c5be9b0ad20edc85fe85247827d72656eabe66c6f71f81ed5b81ba8abd` |
| D1-rdf | 47025 | `ee01d1854e5ac795b308fcda758654d3e3e6fc299540f0f7747b0b35aca48dce` |
| D2-native | 42791 | `ff5f7eebd710203237742318b72f52c334cc922c1876f1fb2493cfcef685ba09` |
| D2-rdf | 47795 | `02da3b0683dbbc7d2adf852c6eb42dbf8af8349950a1c76ef366de0bb5f4184b` |
| D3-native | 42934 | `4c992803ba0e77c5b0e06f3891ff46faf1f2648676d1a6c79d1b100297bccc92` |
| D3-rdf | 46992 | `b3443462cd5fe575370b334f7054099e9d6e2b5f117db5563c88d300de41f5a0` |

本地交接记录：
`/Users/anthonyche/xgap-data/outputs/xgap-independent-handoff-20260927-v1/submission-3890655-user-receipt.json`。

## 结果读取约定

仅读取3890655。启动认证与实际请求分账；资源截断、方法错误、不可评分均保留。
`all_small_requests_processed` 表示支持请求已处理完成，不表示216项全部答对。
回收时核验归档SHA、逐文件索引、支持/结果数量、用量和资源关闭，再更新真实结果表。
不可把8/8入口验收、原后端准入或本次提交当作新增48题答案证据。
旧3886776、小规模本批、F6离线重放及情景估算保持独立。
