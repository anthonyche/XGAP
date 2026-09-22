# XGAP Chapter 6 — Coding Agent Handoff

请基于 [实验执行计划](ch6_experiment_plan_20260922.md) 和 [查询结构规范](query_structure_spec_20260922.md) 准备新版统一算法实验。它们是本轮权威设计；不续跑旧 Exact/Performance 矩阵，不修改论文来迎合已有结果。

## 当前任务

1. 核对仓库最新 commit；已有 registered metadata/probe、bounded plan pools、单步变换和 unified batch 接口可以复用。不要重新实现一套控制器。
2. 输出 inventory：D1 SNB-derived、D2 IMDb–Wikidata、D3 FinBench-derived 的实际资产、版本、许可、映射、规模和缺口；Qwen 27B 是 API，核对精确 `model` alias，不自动代用现有 32B 配置。
3. 实现 LC-QuAD SPARQL 的类型化结构抽取与领域实例化。保留 AST 中的图模式、谓词、聚合、输出和重复语义；详细字段见 query spec。FinBench 优先接 TSR1/TCR1/TCR4/TCR12 的固定版本派生模板。
4. 建立 S01–S08 目录、W1–W4、来源/拒收清单、模板级 split、私有 gold 和独立答案。先用现有小图验证，再构造较大数据。
5. 对齐共享组件 Two-stage：相同验证/loss 条件，语义阶段不使用执行成本反馈，之后固定候选进入同一物理阶段。不得把无条件全字段询问作为唯一对照。LLM-direct 是自建对照，不称外部 SOTA。
6. 接入 noProbe、D=1、明确定义的 myopic 变体；共享资格、资源与完成保护。禁止删 loss 检查来制造速度优势。
7. 输出 pilot manifest 和预计调用/时间/磁盘预算，包含三个数据集的同一实验组。付费调用或全量运行前取得相应执行授权并冻结预算；本交接不自动启动实验。

## 必须记录

每请求：版本/hash、完整 case/config ID、状态、NL 与 controlled 轨道、互斥阶段时间、planner CPU/wall、实际 calls/tokens/bytes、候选/计划计数、cap/fallback、每轮实际动作/观察、loss 证书、selected query/plan 和完整答案引用。不可得的量保持 null。

实际路径与 lookahead 假想分支分开；探测不能查询 gold 或试跑全部物理备选。缓存依赖变化与重新估价记录关联到同一观测。每个请求只执行一个最终计划；reference 构建和 F6 oracle 是独立离线任务。

## 图与数据交付

- E1–E8：效率；F1–F8：效果；S1–S4：附录扩展性；C1/T1：同一实际案例。
- 每个统计图一个 X、一个 Y，三个领域用同一协议；固定方法为系列。绘图用 Matplotlib 矢量 PDF，保存源 CSV/JSONL 和聚合脚本，不填模拟数据。
- 初始目标为三个数据集各 W1–W4 每层 200 个 query–intent cases，即 2400 base cases；先做独立 pilot 决定正式样本数/重复，扫描变体不算新独立模板。
- LLM tokens 用文字/表报告，不占一张图。

## 不可替代的边界

- SNB/FinBench 生成实体不能按姓名伪造到 Wikidata/DBpedia 的真实身份映射；先用同事实分区。FinBench 的自建 risk 标签明确写为合成注释。
- LC-QuAD 是结构来源，不能复用它在旧知识库上的答案为新 workload 的 gold。
- 原版外部方法不调算法、prompt、解码或查询来提高结果。缺少跨平台支持就记录 unsupported，不画该比较；RDF 比较必须让全部方法用同一 RDF 部署。
- D 的默认/扫描在 1–4；较大 N、u、端点数先通过表示/容量准入，不静默截断候选或删失败点。
- F6 的 2 eta 只对固定 Q 和同一 eligible retained plan set 检查；S 图不用于“证明”多项式时间。
- 旧证据、失败、作业和参考快照均保留；不要自动恢复历史 automation。

## 首次反馈给写作端

提交：inventory、模板目录与实际支持表、三个领域各 8–12 个开发实例及独立答案、Two-stage 对齐差异、pilot 运行预算、待用户确认项。不要提交虚构的正式效率/准确率结论。完成这些后，再发布 frozen experiment manifest 开始有授权的运行。
