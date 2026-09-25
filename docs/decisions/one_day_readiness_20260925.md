# 一天内收尾：通用优化、批量覆盖、实验参数冻结

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: plan
- Origin Date: 2026-09-25T02:16:03+08:00
- Verification Status: PLAN; implementation and server acceptance tracked separately
- Version Label: readiness_24h_v1

用户要求从现在起一天内完成本轮优化并达到全量实验启动条件，停止逐题调参。
截止目标：北京时间 **2026-09-26 02:16**。这不是服务器执行已完成的声明。
保留“准备至可全量启动”的边界；不自动启动整个正式实验矩阵。

## 原则与已核对的开源参考

| 开源实现 | 可借鉴原则 | XGAP 今日范围 |
| --- | --- | --- |
| [Apache Calcite](https://github.com/apache/calcite)，[规则与 metadata 文档](https://calcite.apache.org/docs/adapter.html#planner-rule) | 单条规则负责语义等价；引擎负责选择；能力、列来源、唯一性、NDV 与代价信息分离 | 审计现有规则条件和组合，不移植整个 Volcano 搜索器 |
| [DuckDB](https://github.com/duckdb/duckdb)，[优化器说明](https://duckdb.org/2024/11/14/optimizers) | 过滤下推、连接优化、TopN；优化按代数规则组合 | 保留过滤后的键域，按字段活跃性减小投影；Top-K 仍须完整见证证明 |
| [Trino](https://github.com/trinodb/trino)，[代价优化](https://trino.io/docs/current/optimizer/cost-based-optimizations.html)、[动态过滤](https://trino.io/docs/current/admin/dynamic-filtering.html) | 基于统计信息选择连接/分布；限制搜索；把选择性键过滤传给扫描端 | 检查现有半连接、绑定 NDV、源工作量、传输量接线；不新增试跑择优 |

这些系统的成熟度不等于其搜索算法可直接满足 XGAP 的 PTIME 契约。
保留 fixed-D AND/OR 控制器、有界动作/候选/计划表示与 completion fallback。
现有 estimate/move/terminal/completion 缓存已有实现，不重复造缓存或包装成新贡献。

## 通用规则审查表

下面是按规则及交互条件组织的已有实现，不是六项新优化已完成的声明。
只在明确违反这些契约时改代码；性能排序失误保留为实验现象。

| 设计原则 | 现有实现入口 | 必须保留的条件/局限 |
| --- | --- | --- |
| 先减少必要键域，再读取大源 | `runtime/necessary_bind_moves.py`、`runtime/physical_strategies.py` | 保留 FILTER/PROJECT 和列来源；空键不请求；不能提前截断键集 |
| 源内连接下推，跨源做必要半连接 | `runtime/unified_physical.py`、`runtime/native_semijoin.py` | 后端能力和 source identity 相容；外部 membership 在 Top-K 之前 |
| Top-K 减少中间物化 | `compilers/native_spj.py`、`runtime/scheduler.py` | 完整见证与结果顺序证明；不能将普通 LIMIT 随意下推到 join 内 |
| 代价覆盖执行工作，而非只看输出行数 | `planning/relative_source_work.py`、`planning/native_spj_work.py`、`planning/binding_cardinality.py` | NDV、度分布、源扫描、传输与本地工作分开；现有 proxy 不是精确基数或时间界 |
| 同义执行 DAG 去重、按需生成变换 | `runtime/unified_physical.py`、`agent/unified_family.py` | 不穷举乘积、不通过当前题试跑择优；预算耗尽保留可完成策略 |
| 内存、源请求、整题与搜索分别有界 | `runtime/scheduler.py`、`experiments/process_guard.py`、`scripts/run_ch6_admission_census.py` | 内存/时间截断单独报告；搜索的 PTIME 不承诺数据执行能在 60 秒结束 |

小图验收按组合覆盖：空键/非空键、重复实体、偏斜、闭环、跨源 membership、
聚合和排序。已有相应模块测试，除修改影响到其契约外不重跑全部历史实验。
剩余 27 个实际 RDF 输入只做一次离线计划覆盖检查，不按速度、答案或估计优劣筛题。

## 深度是 hyperparameter

正式合同已有 D=1,2,3,5,10；默认 D=2。E5 测 planning wall time，F5 测实际 trace cost。
同时记录状态展开、搜索截止/回退、后端调用、完成率和端到端时间，不增加图数。
SH/GR 保持 D=1 固定参考；TS 不伪造该参数接口。每次请求内 D 固定，不能观察答案
或计时后选择该题最有利 D。固定 D 下的 PTIME 不声称关于 D 多项式；D=10 被
max_states/时间预算截断仍是合法观测，不能偷偷记成完成十层搜索。

## 今日必须完成与停止条件

| 时间窗口 | 交付 | 验收 |
| --- | --- | --- |
| 0–3 小时 | 配置化源/整题预算；失败分类；批量续跑契约 | 旧默认/旧回执不变；未知异常不冒充 timeout；任何续跑先有关闭证明 |
| 3–8 小时 | 通用规则组合矩阵、物理特征与估计器一致性审查 | 小图覆盖空/非空、偏斜、重复身份、闭环、跨源、聚合、Top-K；只修明确共享缺陷 |
| 8–16 小时 | 一次冻结顺序的源端覆盖 census | 记录全部尝试和剩余病例；不按答案选题，不因单个资源超限重新改写；无重复执行 |
| 16–20 小时 | 三域/因子/五方法/F6/预算发布审计 | 全部必要 artifact 和真实运行身份可追溯；缺失不填零、不以支持例外掩盖缺失 |
| 20–24 小时 | 仅修发布阻断并冻结版本 | 输出可启动 manifest 与审计，或逐项实际阻断；不能以到期代替 ready |

正确性、查询身份、权限、数据完整性或后端无法关闭属于阻断。
正常合法查询耗时过长、估计不准或深搜无收益属于可评价现象，不要求优化到全通过。
超时必须区分方法约定的终止和 study/harness 截断。正式可运行性合同与逐题答案成功
是不同字段；旧 full_bundle_admitted 严格成功语义不得直接重命名成新版 readiness。
必须完成发布校验才能宣称 ready；全量输入不能因截止时间而悄悄缩小。

## 预算与公平性

旧 60 s 源请求、120 s worker、3/4 GiB 方法/源内存记录保持原样。
先把这些常量接成可校验配置，保持默认不变。新 census 如采用不同预算，先冻结
同一配置并标记新的运行合同，不能逐题延长到成功。源端、代理、客户端和整题预算
必须一致接线；离线启动时间独立计量。正式五方法使用可比较的声明资源，不能只
对 XGAP 放宽。尚未冻结的新 timeout 数值不写成已生效。

批量安全续跑复用现有首错停止 runner：读取其完整回执，核实关闭/回收，再从
未尝试的下一病例继续；已尝试失败不重试、不覆盖。基础设施或语义身份异常立即
停止，保留未执行部分。完成 census 不代表全部答案正确或已通过正式发布审计。

## 截止前不做

不引入新 learned estimator、不迁移到 Calcite/Trino、不扩大语义范围、不通过修改
数据/样本/参考答案制造成功、不调 baseline 质量、不为单题追求最优物理计划。
不将查到的开源原则描述为已经实现的优化；既有实现、今日修改和实机验收分列。

当前证据：native 24/24 跨版本累计成功；RDF 0–4 累计成功，5–31 已唯一提交为
3874119，运行/终态待回收，不重提。
F6、版本影响、真实 factor 输入及全发布审计仍需收尾。服务器操作与文件交接仍是
外部依赖；24 小时目标不能成为伪造完成状态或跳过准入的理由。

## 本次已落实（服务器验收尚未完成）

- 源请求及整题预算已配置化，默认仍为 60/120 秒。共享观察器允许显式声明更长的
  有界请求；300 秒配置在本地 transport 与两个引擎配置层验证，未用于正式结果。
- 新 census 包装器按冻结顺序推进；只在原段资源关闭可验证后继续未尝试的后缀，
  已尝试的超时不自动重试。证据缺失、关闭不全、答案错误或未知执行异常仍阻断。
- `census_complete`、`all_answers_correct`、`full_bundle_admitted` 与
  `formal_campaign_ready` 分开。[可评价合同](backend_evaluation_eligibility_20260925.md)
  已实现并接入执行单元、混合支持和共享源运行；28 项独立定点检查通过。真实完整
  部署证书尚未生成，旧发布门槛未被绕过，不能把 census 当作已完成发布审计。
- 28 项定点检查通过（预算、分类、关闭、无重复、观察器以及深度/五方法合同）。
- 原 RDF 索引 5–31 的 27 个冻结输入均产生 symbolic plan，0 个直接全边读取节点、
  2–6 个绑定读取节点；零数据库调用、零 LLM、未读取参考答案。节点扫描、数据
  偏斜及绑定扩张仍可能昂贵，尚不构成性能或答案正确性结果。
