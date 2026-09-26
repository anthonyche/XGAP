# 共享入口八结构真实接口验收

2026-09-26，本机通过既有 `qwen3.8-27b` API 完成一次有界验收。
**8/8 entry_admitted**：每题一次真实模型提议，经过正常 compact lowering、公共源
约束下的范围构造、一次付费模拟用户确认，均覆盖其原始隐藏意图。没有模型修复
重试，没有数据库或 planner 调用，没有生成或替换任何论文答案。

## 范围和用量

| 项目 | 实际值 |
|---|---:|
| 独立问题 / 公开结构 | 8 / 8 |
| 模型调用 | 8 |
| 输入 tokens | 21,880 |
| 输出 tokens | 3,534 |
| 模拟用户 scope 确认 | 8 |
| 验收流程墙钟秒 | 18.389 |
| 后端 / planner / 答案执行 | 0 / 0 / 0 |
| 用量未知 / 自动重试 | 0 / 0 |

选择在调用前冻结：按公开模板排序，优先选择当前已选题数最少的可用数据域，
再按数据域和 case ID 打破平局。不读取旧方法胜负、延迟或参考答案来挑选。
D1/D2/D3 为 3/3/2，native/RDF 为 6/2，W1/W2/W3/W4 为 4/2/1/1，
active-anchor/uniform 为 7/1。这是结构接口验收集合，不是五方法论文样本。

| 原问题 ID | 新入口结果 |
|---|---|
| D1-test-active-anchor-bounded_path-000-W1 | entry_admitted |
| D3-test-active-anchor-cycle-000-W2 | entry_admitted |
| D2-test-active-anchor-ordered_star-000-W2 | entry_admitted |
| D1-test-uniform-ranked_count-000-W1 | entry_admitted |
| D2-test-active-anchor-window_edge-000-W1 | entry_admitted |
| D3-test-active-anchor-witnessed_count-000-W3 | entry_admitted |
| D2-test-active-anchor-witnessed_sum-000-W1 | entry_admitted |
| D1-test-active-anchor-zigzag-000-W4 | entry_admitted |

公开问题只追加由公开模板/数据域/scope 生成的边角色说明；原始私有 query 和
nonce 不变，离线封装时仅更新 question hash。模型不能读取 private-user 文件。
范围确认使用相同 source proof 和同一 `snapshot_identity`、`public_scope_request`
组件；没有另建放宽的匹配规则或 gold fallback。

## 封存与边界

- 输入：`/Users/anthonyche/xgap-data/outputs/xgap-entry8-20260926-v2/manifest.json`，
  SHA `2e25c13aa3700a9fa3967070db25dc44653ef0dd22bae4adf85d046d964ddda8`。
- 输出：`/Users/anthonyche/xgap-data/outputs/xgap-entry8-live-20260926-v1/receipt.json`，
  SHA `4fa0d06b577ce49530bac583bff86836dc9cea86ef1679a9c5ce9eac374bf9c6`。
- 运行源对应 `ce7a2dde2496ad5d69fb992d97523be4ba64e04a` 的代码：启动时为
  `a93c549` 加随后提交为 `ce7a2dd` 的 authority 故障停止补丁。回执的
  `stop_reason=completed` 与该实现一致；不把运行后 commit 时间冒充事前提交时间。
- 八个 interpretation 和八个逐题回执的 hash/大小已核验。API 密钥仅通过隐藏输入
  放入运行进程环境，不进入仓库或实验记录。

这证明新公共题意、typed request、等价约束与模拟用户链路在八种结构上实际工作。
它没有测 backend correctness、最终答案、probe 收益、五方法 E2E、规模或并行。
旧 3886776 的每内部方法 17/48 保持原样；不得把本次 8/8 回填为其新增答案。

下一项是冻结共同的新问题文字与 profile，沿原 48 题的域/W/部署分层运行修复版本
五方法小规模评价；维持相同输入和预先声明的支持/预算合同，保留 TS 原查询行为。
不再以一轮完整批次来发现上述共享入口的基础契约错误。
