# 作者 summary 与共同方法服务：2026-09-13

FedUP的作者程序已对完整SF0.1构建一次summary，原生FedUP/FedX方法服务已连接
磁盘源、共同观察器和执行监督。没有改变baseline算法、增加语义、修复答案或重试。

- 新tiny summary准备2.712秒；逻辑源标识固定，作者原生--modify负责映射实际URL。
- 新方法host边界各一次SELECT：FedUP与FedX均返回独立预期的4个账户，EM均1；
  源请求分别3/5，全成功，完整在线约840.751/559.554ms。只说明新地址/host连接
  正确，不能据此声称方法优劣。4个服务进程及观察器全部退出。
- 完整SF0.1作者summary离线准备44.885秒；包含两源named-graph加载、原生summarizer、
  校验与封存，最终receipt写入除外。graph/control分别29/14个summary quads；
  并集42条语句。原数据3158311/338030 triples不变；hash modulo1沿用原配置。
- loader阶段约19.945/4.219秒，作者summarizer约19.685秒；采样RSS峰值分别
  3.116/0.737/2.020GB。配置上限在运行前冻结，所有阶段一次成功，无重试。
- 实际批次控制器3项新风险检查一次通过0.54秒：总预算进入worker守护、最后准入
  的cell不会被准入上限误停、健康会话复用/异常后新会话/固定输入一致/NL不读gold。

[机器可读证据](../../experiments/artifacts/fedup_campaign_preparation_20260913.json)。
代码3f20643（原生离线准备）、bb1f507（方法host）、50f105d（真实批次控制器）。
完整离线准备没有LLM或评价查询；本轮tiny仅2次新连接SELECT，未重跑旧FedX截断题、
FedUP聚合失败或已验收NL/planner门禁。

正式批次以原冻结顺序执行，每题共同180秒/2GiB方法/2GiB源预算，source120秒。
每批最多4个query groups，另有3600秒、12GiB输出和6GiB磁盘保留的采样约束。
原始响应/日志/失败/分母保留；仅清理新建、可由冻结输入重建的serving副本。

首个正式固定语义组FBNS-2-a0baa0e6711f9de3已经另行发车，按XGAP-RDF/FedX/FedUP
各一次执行。该组结果独立记录，不属于上面的tiny接入证据，也不替代整个评价集。
完整NL、原生Neo4j+Fuseki轨、有界FedShop、其余批准实验与后续消融仍有工作。
