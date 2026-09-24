# 正式启动边界：RDF 单题通过，原生中间结果传输待修复验收

2026-09-24，继续遵守“准备至可启动、不执行全量”的授权。旧结果和失败均保留。

**最新原生诊断：**3866035 两次 EXPLAIN 成功，77,767 B 归档已本地 SHA 核验，
两份压缩/原始响应分别校验、无错误/无数据行，服务和副本已关闭。原请求确为
AllNodesScan，索引必要条件使其改为 NodeUniqueIndexSeek。估计基数不等于实际
扫描量；不能由此宣称大图执行已通过或获得多少提速。
原 zigzag/W1 单题复验包 `xgapnativec517451.zip` 已冻结，保持同一完整输入及预算；
用户已校验并提交 **3867351**；其单题仍失败（attempted=audited=1）。
归档 4,879,633 B，SHA `76037e8d2ab5855796772152dba487a47975d60c955918384c0b101c3738f183`。
原始证据已下载并核验，确认第五次请求在 13.476 s 超过 64 MiB 响应上限，
不是原 60 s 超时或 RSS 超限；整题 30.546 s 失败，清理通过。
通用单源 SPJ/最终 top-K 下推现已接入共享 planner 与源工作量估计，25 项局部检查
及 4 组真实 Neo4j 小图有序结果对照通过。完整原题已通过零调用编译检查；用户
已校验并提交单题作业 **3867410**（`ef50ee3`），OnDemand 终端提交记录已确认。
随后用户贴回 FAILED/2:0、71 s、attempted/audited=1；同一原题未通过。
用户随后贴回 worker 原文：一次最终执行、一次后端调用，约 5.050 s 后触发 Neo4j
事务内存上限（当前约 536.9 MiB，阈值 537.6 MiB），HTTP 错误正文 311 bytes；
不是响应体积超限或超时。失败归档待完整下载校验。
通用编译器已修复必需等值条件被 nullable 包装隐藏的问题。28 项定向检查、6 组
真实小图有序答案对照通过；小图 EXPLAIN 原 6 个笛卡尔积/7 次标签扫描变为
0 个笛卡尔积/7 次唯一索引查找。完整源的算子/内存表现尚未验证，下一步仅 EXPLAIN。
见[语义证明与剩余边界](../decisions/native_spj_pushdown_20260924.md)。
不重跑成功前缀、不重提同一失败、不试跑择优。
本地审计：`/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/native-explain-local-audit-3866035.json`。
详见[原生索引证据和包身份](../decisions/native_identity_index_access_20260924.md)。

**最新已核验结果：**3865967 COMPLETED / 0:0 / 4m59s / compt311。
`D2-test-uniform-ordered_star-000-W1` EM=1，guard 21,653.441 ms，5 个源请求全成功，
方法峰值 107,646,976 B、源峰值 766,353,408 B；原数据、HTTP 60s、worker 120s、
source 4GiB 不变，无重试、一个最终计划、零模型调用。源与副本清理通过。
这是单题修复验收，`full_bundle_admitted=false`；剩余 held-out 仍须准入。

新归档 `xgap-node-domain-3865967.tar.gz` 为 1,094,441 B / 216 成员，服务器末行
与本地 SHA 一致：`cdef0792a5620bb6d16977f808ae5104429dc73f32bf9a48e51df29c90e6965a`。
只解包普通文件/目录。F6 独立参考已补齐，本地通过原审计器复核 47 次固定文件读取，
包括全部 12 次实际答案、成本及冻结统计；重算审计字节与服务器原审计一致，SHA
`2d43c684448283bf5f865749807c00f7620a5177c93d6b5779b84d17e6e84ee2`。无新查询。

native 旧失败的第 15 号请求正文已读取：HTTP 200 中含
`Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration`，以及终止前
15,106 行部分数据，不能当成有效完整答案。观察器随后回送时的 BrokenPipe 被分类
为 `harness_transport`；它不能掩盖已存在的源事务超时。worker 在 `cq7/native`
失败，绑定 1,896 个 Movie 身份，原语句以 namespace 拼接成员检查锚定后反向读 RATED。
下一步只用 EXPLAIN 比较原请求与显式 Movie/本地身份索引条件的访问路径；不执行
查询、不用于在线择优、不改变预算。索引假设尚未证实，更不能保证解决真实扇出。

**索引接线进度：**只读诊断已唯一提交为 **3866035**，包 SHA
`345b1cac3b5487dd1e2fada0bab600037786d3861f1cb74126d1261555447b97`，4,038 B。
服务器传送 SHA 校验通过；只复用原冻结 native store、代码 da9329b，8 CPU / 24 GiB，
node-local，worker 120s/3GiB、source 60s/4GiB，最多两个 EXPLAIN，不执行数据查询。
结果因浏览器控制被窗口切换/剪贴板超时中断而待收取，不能重提。

本地已实现有正向类型证明的身份索引入口；7 项定向检查及 4 组真实 Neo4j tiny
等价对照通过。小图 EXPLAIN 明确从 AllNodesScan 变为 NodeUniqueIndexSeek，尚未
外推大图收益。原 RDF 单题的 20 行答案也已在本地独立复核 EM=1。
见[索引访问的语义证明与准入边界](../decisions/native_identity_index_access_20260924.md)。

以下为历史阶段记录，以本段为准。

**单题提交更新：**用户已完成包校验并提交 **3865967**，代码 `da9329b`；现场先后
读到 RUNNING / compt311 / 16s 和 4m50s。尚未取得最终回执。终端与文件页随后显示
空白，直接 SSH 也超时；已请求只读 `sacct` 和日志末三行，不重提作业。下文“尚无
新作业号”保留为提交前历史状态。预期结果包为 `xgap-node-domain-3865967.tar.gz`，
只有作业末行生成的 SHA 与下载字节一致后才进入本地审计。

**下载后更新：**诊断包已传回并完成 SHA 校验，7,991,120 B，546 个成员；只解包
普通文件/目录，未执行包中代码。本地核对 12 组 guard/worker/answer pins 与成本，
重新计算 median/Z/扰动，与冻结文件逐项相等。独立参考文件未包含在下载包中，
答案等价性仍引用已通过的服务器审计，不能称本地独立答案复核已完成。

四计划中位数为 7,582.046 / 7,564.298 / 7,344.870 / 7,369.021 ms。预定 eta=0 时
四内部方法 gap=0；eta=.05/.1/.2/.5 时均为 0.00318516，TS 均 null。该小固定池的
成本差异较小，内部方法选择器相同，不能用这张图证明方法间的性能优越性。

失败源请求已定位：`cq0/native`（User）和 `cq2/native`（Movie）在约 60 s 超时，
没有返回行；后续星形连接因依赖失败未执行。规划约 100.072 ms、CPU 79.438 ms，
不是策略搜索耗尽时间。原请求使用 `?n0 a ?nodeDomain` 加 `VALUES`，再关联检查
已确定的类型，标量锚点过滤在外层。尚无证据认定是星形中间结果不可避免地过大。

本轮最小修复将已明确属于显式 RDF node domain 的正向节点类型编译为常量类型
三元组，保持所有原谓词、DISTINCT、OPTIONAL 属性与最终 typed filter。无标签或
标签不在 node domain 内时保留原域交集，不扩大可见节点。该访问路径允许使用
常量类型索引；是否解决完整 D2 超时仍需原失败题验证，不提前宣称提速。
22 项定向检查通过，涵盖域外类型、双类型、缺属性、多值、原预过滤与绑定插入点。
下一步仅复验这一题，运行配置、数据、预算及已冻结 Java overlay 不变。

**原生回执补充：**已从 OnDemand 下载 `native/receipt.json`，本地 SHA
`b4a52788ba4bf553300aa3b5bd08e989ceb1817a295b499ebf0b45ba1fe850c3`。
前四题 window_edge/W1–W4 都 EM=1，guard 为 8.513 / 3.227 / 3.831 / 3.473 s。
第五题 `D2-test-uniform-zigzag-000-W1` 失败，guard 75.383 s；源观察器记录
`harness_transport:1`，5 次请求、16,621,379 B 已返回正文。方法峰值 274,853,888 B，
源峰值 1,143,754,752 B，均未触发上限；服务/副本清理通过。具体传输错误与失败
请求内容尚需读取，不能归因为算法不可执行或直接当成 source timeout。

`da9329b` 已推送。单题包 `xgapnodeda9329b.zip`（14,853 B）SHA
`9fd02c7f1ad194889b6f5c6f86cf65cd063895c72922a46d2709bd2158dcca1f`，只运行 RDF
原失败题，并收集已经结束的 native 诊断和 F6 独立参考。8 CPU / 24 GiB，节点
compt311，Slurm 40 min；不改变逐题/源预算。包与冻结输入均校验，独立 checkout，
提交记录防重复。因浏览器窗口控制被打断，已请求用户代为上传/提交，**尚无新作业号**。
以下载的原失败 schema/backend 配置作零调用编译检查，两条节点读都已产生常量类型
访问；此检查不冒充完整 profile/catalog 或大图执行验收。

以下保留下载前的原始记录；其“尚未下载”状态已由本段更新。

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
