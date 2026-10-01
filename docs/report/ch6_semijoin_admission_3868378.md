# 3868378：原跨源 W3 修复验收通过

2026-09-24。用户提供 Slurm COMPLETED/0:0，compt311，作业总耗时 00:01:57。
本地随后检查原始归档、计划、参考、响应和关闭记录。没有提交新作业或运行其他题目。

| 核验项 | 结果 |
| --- | --- |
| 精确代码 | `9fbcb8deb29bc0abc782f73d12116b7e663b4afe` |
| 病例 | `D2-test-uniform-zigzag-000-W3` |
| 尝试/审计 | 1 / 1；无重试 |
| 正确性 | 20 行，EM=1，逐行及顺序与冻结参考相同 |
| 计划 | 实际执行计划等于服务器零调用选择，也等于此前本地零调用选择 |
| 跨源过滤 | 实际 Fuseki 响应经 Boolean false 过滤得到 1,256 个键，等于最终 native membership 参数 |
| 规划 | wall 310.296 ms；CPU 280.371 ms；179 expanded states |
| 查询执行 | 41,428.110 ms |
| worker 总耗时 | 44,683.548 ms，含进程启动/读文件等，不与规划/执行简单相加 |
| 离线新服务准备 | 47,509.445 ms，单独报告 |
| 调用 | 一次最终计划，5 次后端请求，零模型/澄清；无试跑择优 |
| HTTP 响应 | 累计 14,267,466 B（约 13.61 MiB）；最大单次 11,162,049 B |
| 最终 native 响应 | 8,479 B，20 行，HTTP 观察耗时 29,779.688 ms |
| 采样峰值 RSS | 源组 1,305,346,048 B；方法 275,099,648 B |
| 清理 | 所属源进程均终止/reaped，观察器停止，可重建 serving copies 回收，冻结输入和查询证据保留 |

源内存设置、worker 120 s / 3 GiB、source 4 GiB、HTTP 60 s / 单响应 64 MiB
与原失败 3868312 相同。没有提高预算，没有缩减 MovieLens20M 或修改原题。

原始五个响应对应节点表、节点表、锚点边、外部属性、完整 native 结果；
响应行数分别为 27,278、138,493、1,896、1,896、20。
前两个节点响应仍合计约 13.42 MB；最终原生请求仍约 29.78 s。
这说明已恢复资源可行性，尚不是低延迟已优化到位的证明。没有在本轮继续改写或重跑。
HTTP 观察耗时不等于纯引擎 CPU；没有由 read_bytes/缺页推断扫描行数或 I/O 等待。

## 证据与核验边界

归档：`/Users/anthonyche/Downloads/xgap-native-semijoin-3868378.tar.gz`
642,459 B，SHA-256
`8a9ce6da2fc9f488e503632b603e5bcea7a71907f1391d5f23a4bc5ad056919e`。
67 个普通文件，安全解包 1,881,303 B；压缩与解压后的响应哈希均匹配。

审计：`/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/semijoin-gate-3868378-audit.json`
SHA `c32844af3310e976fe2a0cf4d731e8df3410c798d7d7b9d6b538d873856176e9`。
30 个可用 pin 通过；11 个外部引用文件不在本地，明确列出，完整 source stores
没有在本机重算哈希。归档完整性、冻结源身份和服务回执不等同于本地重新装载全库。

查询 SHA `f9e5ee2a4e30a9a04f4bcf5801602ef7df7f3282a7eaedb7826b5070301c3085`；
源快照 SHA `285d51732cdb259eff176ece1dc541cdeca29d51781e55d1cb3010cbbe8894a7`；
计划 SHA `847b487e70f5ea21cab2ba33db57f372ae9f6a333cd99800f9c4ab61aa204322`；
冻结估计器 SHA `d45af62450f999f25542c13defb147517075806aa77f978fd07f28d483f50401`。

`worker.bytes_moved=0` 只属于其局部计数，不能替代 HTTP 14,267,466 B。
RSS 为采样进程组总量，可能重复计入共享页，不是精确事务内存峰值。
Neo4j 私有进程组清理使用 SIGTERM 后 SIGKILL，回执确认已终止；不涉及原始源库。

## 能支持的结论

原 W3 在 3868312 因大规模入边响应超过 64 MiB 而失败；新策略在不变输入/预算下
正确完成，证明外部过滤未被跳过，跨源 membership 与 native 完整查询下推接线有效。
旧失败执行在 27.538 s 中断，不能作为成功方案的延迟基线，因此不报告提速倍数。
这是一次完整源单题工程准入，`full_bundle_admitted=false`、`paper_result=false`。
后续仍按[执行形态预检](../decisions/resource_shape_preflight_20260924.md)处理剩余覆盖，
本轮不启动下一批或全量实验。
