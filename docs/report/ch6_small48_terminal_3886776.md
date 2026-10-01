# 3886776 原始验收、共享入口修复与实际 probe 结果

2026-09-26。应用处理完全部 216 个适用请求，`all_small_requests_processed`，
216 sealed、0 unsealed、用量完整。下载归档 8,428,213 B，SHA-256：
`a98b4e56389a5d5667a8aca13498d76a51a34c64cc6a41f70a6e2de331d833c8`。
已核对 2,970/2,970 文件 hash/大小、全部 terminal/outcome/score pins、192 个内部
core 及 query-loss pins。应用 success 指处理结束，不能当作全部答案正确。

运行代码 b86ada5；本批不含后续 7eba154 或本次修复。旧配置、题目和结果不变。
这是 48 道 authored 小规模真实图问题，每域 W1–W4 各四题；不是 800 题结果，
也不是官方 benchmark query-card workload。TS 的 24 个 native 不支持位置未执行。

## 实际结果

| 方法 | 正确回答 EM=1 | scope 拒绝 | proposal 拒绝 | 预算截断 | method_error |
|---|---:|---:|---:|---:|---:|
| XGAP | 17 | 27 | 4 | 0 | 0 |
| NP | 17 | 27 | 4 | 0 | 0 |
| SH | 17 | 27 | 4 | 0 | 0 |
| GR | 17 | 27 | 4 | 0 | 0 |
| TS | 0 | 0 | 0 | 21 | 3 |

每内部方法 D1 为 8/16、D2 为 5/16、D3 为 4/16；同一道题四方法状态完全相同。
68 个实际回答全部 EM=1；总体每方法仍是 17/48，不能把条件正确率当覆盖率。
TS 21 个预算截断的裸 score 为 0，但 terminal 和正式摘要正确显示 null；保留该
掩蔽，不把观测上限截断改成答案错误。另三项方法异常为两个 RetryError 和一个
HTTPError，均有 federation upstream HTTP failure，模型通道未报告认证失败。
原精简归档省略失败响应明细；后续补充归档和原查询回收已完成，见下节。

### TS 三项异常的最终诊断

补充包 `xgap-small48-ts-errors-3886776-v1.tar.gz`（3,483 B，SHA-256
`47968c954b474dd686ea7028c2e55f8fe3437d4894b0f21eb6e98f82911b6484`）
的四个成员 hash 全部通过，三组 trial/worker/phase seal 与主归档匹配。
七个 HTTP 500 响应都完整返回 `MalformedQueryException`，单请求 27.982–56.708ms。
两条探索查询各被同一作者过程重复提交三次，最终查询一次；wrapper retries 仍为零。

首次补充包只保留查询 hash，不能据此区分入口解析与 FedX 内部错误。后续通过只读
命令取回三个原查询，194/260/1,216 B 及 SHA 全部与冻结 observation 完全相同。
用冻结的 RDF4J/FedX 5.1.2 JAR 进行本地 parser-only 验证，三条全部拒绝：

| TS 请求 | 解析原因 | 查询 SHA-256 |
|---|---|---|
| D1 bounded_path/W4，探索阶段 | `ORDER BY ?cnt DESC` 结尾缺少 DESC 的括号表达式；EOF，line 6 col 36 | `5d2b2559f20eaed2d10bf04211a3157d5a22dcb16c7ccae2979a79a069fd6fc4` |
| D3 bounded_path/W1，探索阶段 | `STRCONTAINS` 非合法内建函数语法；line 9 col 13 | `375d166bb3caaea8dbbb0e4793a7a996724758f0a35dfc7dca46532df867373b` |
| D3 cycle/W3，最终查询 | 正文停在注释，查询未闭合；EOF，line 45 col 50 | `568fe0a0d126dad7c03d3859d6913e4615990e0fb53e1f96b3516ef143f0ae5e` |

因此这三项不需要归因于数据库超时或内部联邦子查询；原始输入在执行前已经非法。
接口还有独立的诊断缺口：bridge 的纯文本 500 未被作者代码识别，两个探索失败最后
呈现为 `RetryError`。新增阶段/异常类/查询 hash 日志，保持 HTTP 状态、正文、查询
和基线重试行为不变，不修正基线 SPARQL。采集器 v2 保留有界的原始公共 SPARQL，
不再因只有 hash 而重复取证。旧 jar/运行结果均不覆盖。

上述验证没有模型调用、没有答案查询。三项仍保留 method_error，其余 21 项仍为
预算截断/null；不能把这三条的语法结论推广到其余未取得答案的 TS 请求。

总调用 664，输入 token 1,110,753，输出 token 130,573，均已从原始记录重算一致。
四内部方法各 48 调用，输入 124,007、输出 21,986 token；TS 使用剩余调用和 token。

## Probe 真实生效，但本轮未显示总收益

XGAP 7 次实际 probe 分布于 5/17 道进入 planner 的题；NP 为 0；SH 为 7 次/7 题，
GR 为 23 次/7 题。17 题 XGAP/NP 候选族 hash 和候选顺序一致，XGAP 注册 63 个
候选 probe 目标；所有实际 probe 结果属于 `large`。不是“probe 未激活”。

仅在 17 道共同成功题上计算每题平均值（一次重复；MB=10^6 B）：

| 方法 | E2E 秒/题 | planning 秒/题 | execution 秒/题 | source calls/题 | source MB/题 |
|---|---:|---:|---:|---:|---:|
| XGAP | 18.205 | 6.331 | 6.621 | 4.000 | 9.403 |
| NP | 17.977 | 5.164 | 7.608 | 3.412 | 8.485 |
| SH | 12.828 | 1.250 | 6.375 | 3.706 | 8.144 |
| GR | 16.257 | 2.040 | 8.315 | 4.941 | 9.775 |

XGAP 相对 NP execution 平均减少 0.987s，但 planning 增加 1.166s，E2E 增加
0.228s。实际选 probe 的五题，XGAP/NP E2E 为 27.619/25.521s，execution 为
13.214/13.240s，planning 为 9.178/7.244s；现有观测不支持“付费 probe 值得”。
17 题有三题最终执行图不同，其中两题属于实际 probe 子集；不能把所有改变都归因
于 probe。这些条件均值不覆盖入口失败、TS，也不能填充未测的因素/规模/并行曲线。

## 一次归类的 124 个入口失败

| 根因 | 独立题数 | 四内部方法请求数 | 处理方式 |
|---|---:|---:|---|
| 对称比较/声明顺序的表示差异 | 3 | 12 | 已有 identity-v3 与 public edge selector |
| 业务唯一键与技术 identity 被当成不同语义 | 14 | 56 | 验证公共源唯一键后等价比较 |
| 非空单边 contribution COUNT 与 DISTINCT edge key | 4 | 16 | 在非空、唯一、函数依赖证明下比较 |
| W4 把 witness 边也误限到 EARLY/LATE | 4 | 16 | 公开说明主边未决域及 witness 基础关系 |
| 题目使用 e 的属性却未声明 e 对应哪条边 | 2 | 8 | 版本化公共边角色说明 |
| 关系变量同时声明为节点／关系缺失 | 4 | 16 | 公开标签枚举及明确变量角色；不猜端点 |

新版源证明已在全部 192 个内部请求上离线重放：152 个请求（38 题）通过 scope，
原先 68 个成功请求（17 题）全部保留，零回退；新增覆盖恰为 84 请求（21 题）。
剩余 16 个 lowering 拒绝、16 个 W4 locator 拒绝、8 个真实角色错配保持拒绝。
这是范围检查修复证据，不代表新增 21 题已经完成 planning 或得到正确答案。
其余 40 项不能靠扩大等价规则“修好”。此次不增加逐题硬编码，不改 estimator
来绕过入口，也不把未执行的查询计作成功。公共候选真正遗漏意图时仍保守拒绝；
开放范围恢复工具不在本次偷偷补成 gold fallback。

## 已完成的通用接线

- `PublicCompactConstraints`：仅由冻结 materialization、fact-index、schema、mapping
  与 source load 版本证明；paid authority 与 post-seal query-loss 使用同一合同 hash。
  scope confirmation 的签名和后续 scoped user 同样绑定该 hash。
- 节点只在同类型、同唯一非空 key、eq/ne 时归一。COUNT 只在单贡献边且所有保留
  变量受该边/端点决定时归一；nullable、非 key DISTINCT、额外 witness 分组、多个
  contribution key 均不放宽。scale4 的边业务 ID 重复，v1 合同明确拒绝该规模。
- 新 `frozen_compact_model_public_contract_v1` 前端组合原精确等价 lowering 与公共
  node/edge 标签约束，仍一调用、无自动模型重试；实际 prompt/schema hash 记录。
  非法回复原样保留并拒绝，绝不删除变量或推测缺失端点。
- 新公共题目版本说明 e/f/g/h 和 path 角色；既有题目不覆盖。对旧题追加说明只用
  公开模板和公开 scope，不从 private-user.query 重建公开题目。
- E7 live-probe 价格配方独立发布：五方法、25 个图位置、136 个待运行请求；NP/TS
  固定参考重用，不改变候选先验/阈值/题目来强迫优势。尚无这条扫描的测量数据。

六个真实域/部署和 quarter 共七个公共源证明检查通过。测试与封存记录重放为
离线代码证据，不算论文新实测。本轮未调用模型、未提交服务器作业。

## 下一项与文件

1. 全部 192 个封存请求重放已完成，原成功题无回退，旧实验记录不修改。
2. 对新的公开题意、类型请求及范围合同做最小真实接口验收，再冻结下一份共同
   小批次输入与预算；不以重跑旧 216 项的方式发现契约基础错误。
3. TS 三条原查询已经完成同版本解析核验：保留语法失败，仅补错误诊断，保持基线
   算法、预算、查询文本和全部旧失败，无需重跑 TS 来定位这三项。
4. 按已测单元更新 CSV；E7/scale/parallel 保持独立因素运行，不能从本批均值推曲线。

原始验收：`/Users/anthonyche/xgap-data/outputs/xgap-small-real-20260926-v1/raw-audit-3886776-v1/audit.json`。
配对结果：同目录 `paired-success.json`。诊断：
`/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/audit-small48-3886776-v1/`。
完整修复重放：`/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/audit-small48-public-contracts-3886776-v1/audit.json`。
归档精简时省略了服务器上 16,136 份细粒度文件（211,409,857 B）；它们不是已下载
验收的一部分。本轮尚不能宣称全部实验 ready，主要剩余阻塞已收敛到共享入口新
契约的真实验收；三条 TS 原始错误已定位，不再据此逐题优化后端。
