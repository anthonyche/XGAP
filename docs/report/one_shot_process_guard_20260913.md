# 9月13日：请求守护与失败计分边界已接通

017a0d2新增通用进程守护，并把已有XGAP单请求入口接入这个显式接口。它解决的是
单次socket超时无法约束整题线程/协调器执行的问题，不改变planner、解释或baseline
算法。原入口与历史计时含义保持不变。

## 现在可执行的行为

父进程只启动一个请求worker，用独立进程组管理生命周期。初始冻结预算为180秒
worker wall、采样进程组RSS2GiB、日志1MiB、64个进程，采样间隔50ms；异常时先
TERM，0.5秒后必要时KILL。保留stdout/stderr、部分原始provider/backend文件和
独立终态记录；主进程退出但子进程仍在运行也不算完成，不自动重试。

被中断或在配置预检阶段失败的请求仍保留dataset、题目、分组和原分母；已有评分器
可直接评分。执行失败对空gold也为0，不能把未执行伪装成正确空结果。缺失用量标
unknown，原始部分文件保留，不伪造0次付费请求或历史模型用量。

## 新证据

五项定向检查一次通过，0.82秒。它们实际启动本地短进程，验证正常/非零退出、
忽略TERM的父子进程被截止守护终止、无关进程不被影响、RSS/日志超限、主进程
退出残留子进程、监控故障保留失败并清理，以及中断请求对空gold计0。没有重新跑
原LLM、数据库、训练、baseline或软件回归门禁。

随后在已冻结的完整FinBench profile上做一次新的**零调用预检**：

| 观测 | 结果 |
|---|---:|
| 守护worker完成时间 | 2,871.967ms |
| 方法worker进程组采样RSS峰值 | 250,527,744字节（238.922MiB） |
| 模型、数据库、训练、最终计划执行 | 全部0 |
| 状态 | preflight_passed，退出码0，进程清理完成 |

该请求为新手写的接口检查语句“List account business IDs.”，不属于冻结120题，
未读取评价答案、未生成模型解释或执行查询。实际worker与全部过程文件经过审计，
进程身份已确认不再运行。本预检不产生任何方法准确率或查询速度数据。

## 计量和剩余工程边界

2.872秒是独立worker的观测完成时间，包含Python启动、profile/catalog读取和其
记录写入；父adapter在启动前的budget/input pin校验、最终汇总写入位于这个计时段
之外，不能直接把它叫作完整方法E2E。正式共同runner需同时记录这些外层成本。
清理另列。RSS为采样的进程组内存总和，会重复计共享页，也可能漏掉短峰值，不能
声称严格OS内存隔离或精确峰值。

共享数据库、常驻外部方法server和远程LLM均不在该worker测量/终止范围。不能拿
薄HTTP客户端的RSS和完整FedUP JVM的RSS混比。异常终止后，campaign必须确认外部
工作静止，或按协议清理/重置自有服务并记录恢复费用，再运行下一题；仅杀客户端
不能证明服务器查询已停。这个服务边界仍待接线，不能清除quiescence标记冒充完成。

下一步：真正连接同事实RDF的XGAP多endpoint执行/估计身份，完成共同外部输入与
原始结果规范化评分、托管服务资源/观测和失败后的静止屏障，再装载并执行真实主
评价。baseline保持作者算法、语义与原生重试，如实报结果。120题分母、旧负结果与
曝光不变；消融仍在主评价后。整体Goal未完成，campaign_ready仍false。

## 证据

- [冻结预算](../../experiments/protocols/one_shot_request_budget_v1.json)
- [守护契约](../decisions/one_shot_process_guard_v1.md)
- [提交审计](../../experiments/artifacts/one_shot_process_guard_20260913.json)
- 根目录：`/Users/anthonyche/xgap-data/finbench-serving-guard-preflight-20260913-v1`
- audit SHA-256: `4545a19cc139a9cfb9af3b8141d6c15886cb1bb1162b1801c402b8a0b3984a0b`

本轮所有进程均已终止，未启动数据库或模型服务。
