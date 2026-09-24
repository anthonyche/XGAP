# 正式启动边界：F6 通过，D2 新测试题仍阻塞

2026-09-24，继续遵守“准备至可启动、不执行全量”的授权。旧结果和失败均保留。

## 已观测结果

|作业|代码|结果|意义|
|---|---|---|---|
|3865881|f04309d|COMPLETED，0:0，2m31s，compt311|D1 同一完整 Q、4 个原计划各 3 次的 node-local 成本测量与原始证据审计通过|
|3865863|0ac3f60|FAILED，2:0，11m38s，compt311|D2 held-out 准入未通过；不能启动正式全量|

F6 的服务端回执记录 12 次成功测量；答案、逐次原始成本、median/Z/误差扰动和服务
关闭审计通过。成本来自冻结池内离线执行，不反馈在线规划。四内部方法共用终端
选择器；TS 无可比估计器接口时仍为 null。这是 F6 可评分材料，不是端到端优势结论。
完整数值尚待下载后复核，不沿用旧 NFS 成本冒充本次 node-local 成本。

服务端文件身份：

- `formal-f6-node-local-v1/D1/cost-audit.json`：
  `2d43c684448283bf5f865749807c00f7620a5177c93d6b5779b84d17e6e84ee2`。
- `formal-f6-node-local-v1/D1/sensitivity.json`：
  `89ccc29fc14e5bb050ffce7abc84e68de4f29647e64eaa5bbd24488c9e0a19d5`。

D2 RDF 在第二个实际测试题 `D2-test-uniform-ordered_star-000-W1` 首错停止。
其回执记录 2 次失败源请求，类别为 `source_timeout`；方法采样峰值 40,038,400 B，
源采样峰值 1,079,513,088 B，观测状态为 `within_observed_budget`。因此这次已观测
失败是查询超时，不能写成再次触发 RSS 上限。源进程与 node-local 服务副本清理通过。
`full_bundle_admitted=false`，RDF 总题数 32。native 分支独立执行，其逐题结果尚未读取；
整个作业失败不能据此推断 native 也失败。

D2 冻结 runtime：`formal-release-admission-v1/D2/rdf-runtime.json`，SHA
`2629c7bd23ae5eef2e0bfe084f8814eb7c75bfd9805e4b2fe664bc7221eb5f37`。
实际 source-ready SHA
`63b55db1491e6fe859052ca285992c46d57228fe2e40c0801d013912d9090afa`。
保持原完整 MovieLens 20M、HTTP 60 s、worker 120 s、源 4 GiB，尚未放宽预算。

用户已在服务器封存 RDF/F6 与失败题输入：
`/home/hxc859/xgap-release-evidence-3865881-v1.tar.gz`，SHA
`619d8194d38a6c6070d7f592aa0cae772bda768f90e0a616299fca05258db626`。
这是用户终端提供的服务端哈希；本地字节校验尚未完成。浏览器控制先后返回
`noWindowsAvailable` 和专用文件页连接超时，不能声称证据已下载。

## 同期发布接线

发布审计要求五方法各自的非负 API/token/墙钟预留、单次请求可容纳预算、明确的
source-session cell 上限及合法重复索引。D2 已有独立 ordered-adjacency 参考引擎
加入可接受参考类型，避免错误拒绝已有独立参考；没有更改参考算法或答案。
准备入口支持冻结方法子集，用于单独生成 TS 固定 NL 参考，避免重排四内部 NL 请求。
全图五方法位置的完整性仍由总 release 审计检查。

最后一次改动后针对执行单元、参考/预算准入和会话续跑的 5 项测试通过，零模型/
源调用。此前相关合同检查保留；不追加无关整套回归。

## 下一步和停止条件

1. 下载并核对上述归档，从失败题的实际计划、源查询、guard/worker 和 I/O 观测定位
   超时原因；先区别不良访问路径、缺少等价计划和不可避免的真实工作量。
2. 有证据后再做最小语义保持修复，先 tiny 正确性再仅复验该失败题；不重跑旧 pilot
   或整批，不按答案/胜负换题，不盲目扩大超时或内存。随后继续未尝试的题目。
3. 复核 native 结果，完成实际部署准入；将 F6 审计与同 prepared/runtime/storage/
   source 预算的 D1 unit 绑定。
4. 冻结其余实际 units、全部图中位置、支持子集及全局预算，运行发布 dry-run。

目前没有完整通过的正式 release，也未执行任何正式五方法全量任务。只有实际
release audit 无缺失且全部通过后才可报告 ready。
