# XGAP 多 RDF 实例里程碑与暂停交接 — 2026-09-13

## 本轮结论

**XGAP 已能在两个独立 Fuseki 端点上，用冻结估计器选择一个最终计划并跨源执行。**
三类小图查询均与独立预期答案一致；这补上了同事实 RDF 评价轨的端点与估计器接线。
这是确定性工程集成证据，尚不是总体 NL 准确率、提速、可扩展性或优于 SOTA 的结果。

代码提交 `f3857093948842e8525ef569703e5037f53ce88a`；
[设计与算法边界](../decisions/rdf_instance_estimator_v1.md)、
[可审计结果](../../experiments/artifacts/rdf_instances_native_20260913.json)。
用户最新指令为本轮完成后暂停，**2026-09-14 12:00 北京时间恢复**。
原 heartbeat 已改为中午恢复，期间不启动下一轮工作；整体 Goal 仍未完成。

## 实现了什么

- **端点与引擎分开。** `rdf_graph` 与 `rdf_control` 使用各自地址、数据库、源身份、
  快照和统计。已有 compiler/client 能处理这一点，本轮复用其能力，并在 profile
  加载时拒绝端点 capability、client engine 与估计器 reference engine 不一致。
- **复用冻结估计器。** 先按实际端点分别计算工作量，再把同引擎实例的特征相加，
  映射到原 Fuseki 特征维度。原模型文件、32 条训练观察及权重完全未改，没有新训练。
  记录实际特征与投影特征；缺失统计、源身份不符和未训练类别仍明确 unavailable。
- **离线发布 RDF profile。** 从冻结 serving 配置和同事实文件派生 RDF 配置，校验
  load 文件，复用 catalog/prompt，不读 query/gold/答案，也不重建数据或调用服务。
  两模式均可加载。本轮只实际发布 tiny profile，完整 SF0.1 的 RDF profile 尚未发布。

这个特征投影是有界、多项式的，不扩大原候选域，也不运行候选来选优。源和实例迁移
未校准，**没有实际最优计划的近似比保证**；非负特征的单调性不是实际时间的保证。

## 本轮实测长什么样

复用已接受的 **8 个实体、16 条关系**小图，两份 RDF 分别加载到两个独立服务进程。
每类产生 6 个合法候选，全部只做估计，均在服务启动前选择一个 coordinator 计划。
没有执行其余候选。每条答案都是结果封存后才与独立 reference 比较。

| 查询含义 | 独立答案与实际结果 | graph / control 调用 | 规划 / 最终执行 ms |
| --- | --- | ---: | ---: |
| 转账汇总（F1） | 公司 1：账户 2 金额 66、账户 3 金额 9；exact | 4 / 1 | 19.496 / 148.967 |
| 时间递增路径并关联介质（F2） | 4 行，保留账户距离 1 与 2、对应 PHONE 介质；exact | 4 / 2 | 22.470 / 70.954 |
| 高风险介质关联后的公司金额排名（F3） | 公司 1 金额 56；exact | 4 / 1 | 19.360 / 48.813 |

三次最终执行，共 **16 次必要后端调用**；模型、baseline、采集、fit、当前题 probe、
替代计划执行、自动 retry 和数据重建均为 **0**。零模型调用是因为本轮验证确定性
planning/execution 链，输入为手写语义程序；普通 NL 的已有真实成功没有重跑。

这些是每题一次的开发观察，没有重复取平均。预测执行时间分别为
25.825 / 31.084 / 25.825 ms，不能用三次观测证明排序质量或迁移校准。
首次请求包含服务初始缓存等影响；不能与旧 native/NL gate 直接计算提速。

Tiny profile 准备 43.350 ms、双服务启动 12,521.493 ms、两次数据加载 65.797 ms，
单列为离线/部署成本。表中规划时间包括候选构造、全部估计和相关序列化；执行时间
围绕 scheduler。它们不等于包含 NL、profile 加载及记录汇总的完整端到端时间。
新实例估计器的 `prediction_elapsed_ms` 暂不含最后 deployment provenance 序列化，
外围 `planning_ms` 已包含；正式共同 runner 应使用完整外层时间并保持阶段边界准确。

## 检查、复现与清理

只新增并运行 5 项接线风险检查，**首次全部通过，0.47 秒**：原路径恒等投影、两个
源各自统计及三类计划编译、身份/快照漂移、引擎与 capability 不符、冻结 load 漂移。
没有重跑旧成功门禁。新 live harness 第一次执行成功，未做失败后的重跑。

实际执行命令（记录供复现，不在暂停期重跑）：

```bash
PYTHONPATH=src:tests /tmp/xgap-directed-tests.qU2YfW/venv/bin/python -m pytest -q tests/test_rdf_instance_work.py
PYTHONPATH=src:tests /tmp/xgap-directed-tests.qU2YfW/venv/bin/python scripts/check_rdf_instances_native.py --output-root /Users/anthonyche/xgap-data/rdf-instances-native-20260913-v1
```

完整输入、计划、逐调用记录、答案、加载和停止记录位于
`/Users/anthonyche/xgap-data/rdf-instances-native-20260913-v1`。
Profile SHA-256：`a636cc548c6c11c6181f6a2745fbd9d7903a10417d271c57040fbc63d55bd72a`。
验收 audit SHA-256：`2203c63830343b6bc5f57e2293882d1cf2c543f12473e93348fc1dee34243fe5`。
输入封存校验不变；进程 28449、28471 均经 SIGTERM 退出，收尾检查无其存活进程或进程组成员。

## 当前整个系统到了哪里

| 环节 | 已有实现和证据 | 尚未取得的证据或尚缺接线 |
| --- | --- | --- |
| 普通 NL → grounding → 估计选优 → 一次执行 | 既有真实 LLM + Neo4j/Fuseki 金融小图成功，保留所有首次失败 | 新 population 的总体 NL 准确率、精度/性能 Pareto |
| 多 RDF 实例确定性链 | 本轮三类真实双端点全部 exact | 完整 SF0.1 实例配置发布、正式服务装载及运行 |
| Planner / estimator | 有界 Ptime 候选域，冻结模型选择，不在线试跑全部候选 | 独立测量排序质量、regret 和随规模变化的表现 |
| 数据/catalog/statistics | 完整 SF0.1 18 表、55,604 实体、309,577 关系及 59,587 catalog 已冻结 | 无需继续重建；后续按版本加载 |
| Population/reference | 120 组与 24/48/48 split 已冻结，NL 与独立 CSV reference 分离 | 按协议执行，保留评价 33 空/15 非空，不重抽 |
| 运行与计分 harness | 请求记录、失败分母、金额规范化和 worker 预算守护已有实现与验证 | 外部方法共同输入/评分接线、完整方法计时、常驻服务资源和异常后静止屏障 |
| 外部 SOTA | FedUP/FedX 作者实现已固定并能运行，原生失败与限制保留 | 与 XGAP 同 population/同事实的正式对照；不优化 baseline 结果 |

因此，核心骨架已有实际运行证据，**正式评价准备仍未全部结束**。
已有功能尚未做整体评价，与共同 runner 尚缺接线，是两种不同状态。
`formal_campaign_ready=false`，本轮没有新增论文主实验或消融结果。

## 明日恢复后的顺序

1. 补共同外部输入与结果评分，明确同事实和语义可比边界；不改 baseline 算法或答案。
2. 补完整方法外层计时、托管方法/数据库资源与异常后的静止检查。worker 被终止不能
   代表远程查询已停，不能直接带着残留工作进入下一题。
3. 发布完整 RDF profile、按已批准协议装载和运行 FinBench native / RDF / FedUP / FedX；
   开发排错仍用小图/replay。随后有界 FedShop，消融最后；GrailQA 不阻塞。

暂停至 9 月 14 日 12:00 后，距离原定 17:00 核心/评价接口目标只剩 **5 小时**。
恢复后优先完成上述实验启动必要项，不再扩充通用功能。9 月 18 日真实论文实验目标
保持，但本轮接线成功不构成对最终准确率或提速结论的承诺。
