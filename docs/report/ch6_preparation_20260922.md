# 第六章实验准备：首次交付（2026-09-22）

本轮完成的是新实验计划的开发准备，**没有运行正式效率/准确率实验**。
已落盘用户三份原文、更新 Goal/架构/roadmap、对齐共享组件方法，生成三域小工作负载，
并得到 29/29 个本地编译执行与独立参考一致的结果。后端是便携 RDFLib adapter，
不是新数据集的真实 Neo4j/Fuseki 服务。付费模型调用和后端网络请求均为 0。

[机器可核验记录](../../experiments/artifacts/ch6_preparation_20260922.json)保存文件 hash、
失败记录、本地 gate、inventory 和预算提案的位置。原始数据、私有 gold、完整 reference
留在 `/Users/anthonyche/xgap-data/`，没有上传 Git。

## 数据实际到了哪一步

用户同意 D2 可以替换为更合适的来源。采用 MovieLens-derived 开发轨，详细理由、
官方许可链接和语义变更见[补充决定](../decisions/ch6_dataset_and_methods_20260922.md)。
正式候选是稳定 MovieLens 20M，未把 latest-small 当作正式评价数据。

|领域|本轮小快照节点 / 原关系|开发实例|实际模板族|目前边界|
|---|---:|---:|---:|---|
|D1 SNB-derived|54 / 64|9|8|官方 pinned CSV；同事实 gender 分区；无合理 SUM 字段，拒收 1 题|
|D2 MovieLens-derived|67 / 64|10|6|4 个匿名 user 的真实评分、movie 属性；没有 IMDb 演员数据或已验证 Wikidata 映射|
|D3 FinBench-derived|105 / 64|10|9|既有 v0.1.0 SF0.1 中固定前缀的真实转账及账户属性；不是完整 SF0.1 测量|

D1 官方测试包固定 `11db98cc2ba14c33492f6c0c34e68c8be7e22e5f`，33 文件共 4,018,530 bytes，
逐文件比对 Git blob 和 SHA-256。MovieLens 下载 zip 为 978,202 bytes，实际包含
100,836 ratings、9,742 movies、610 users；本轮开发仅取预定义的 64 条评分。
D3 已有完整 serving materialization 记录是 55,604 个实体、309,577 条关系；
这里只核对已有记录和源包，不把它写成今天的新装载或新实验。

每域均有 W1–W4、template registry、public cases、controlled families、私有 gold、
独立 references、rejections、template-family split 和封存 hash。全部开发族都留在
development，正式 test 清单为空。当前候选数实际为 1–16，**不称已经满足所有
N/u 扫描水平**。W4 的 EARLY/LATE 是固定时间阈值划分的不同关系集合，不是副本位置。

开发模板为 authored domain derivatives；SNB 的 COUNT 辅助字段 value=1 是固定计数
表示，不是数据中的真实数值属性，不参与歧义/字段扫描，也不用于 SUM。
FinBench 原始 TSR1/TCR1/TCR4/TCR12 的逐 card 忠实派生仍待核对；现有无时间路径和
完整结果投影不得冒称原版 TCR。D2 二部评分图不强补三边 cycle/同类型 traversal。

## 工具与方法

- LC-QuAD：固定作者版本和 6,578,362-byte test 文件，以前 128 条的 Wikidata/DBpedia
  两字段作开发结构材料，共 256 条 query。保留 raw SPARQL、parser AST、resolved algebra、
  typed 参数、输出/聚合/排序/重复合同；支持结构归类与严格 typed 代入，不通过正则删 IRI。
  124 条完成抽取、132 条拒收。**抽取成功不代表领域 compiler 准入**；OPTIONAL、
  qualifier、子查询等保留理由。首版结构分类记录也保留，v2 修正有向 chain/star 的区分。
- Two-stage：与 XGAP 相同的资格和 loss 合同。语义阶段不读执行价格作选择，达到资格
  就按固定 ID 选解释，然后进入相同物理阶段。定向测试确认可以只披露 2/3 字段；
  执行价格放大不改变语义决策。旧全字段 sequential ID 保留，仅用于历史复现。
- noProbe/shallow/myopic：接入同一控制器及严格方法/配置检查，完成保护不减弱。
  noProbe 保留 metadata，shallow 与 D=1 是同一设置，myopic 只看非终端即时估价。
- LLM-direct：新增一个 proposal→相同物理规划→一次执行的入口，不访问意图权威、
  不修补/重试。内部也不伪造 coverage；返回的 intent certificate 为 null。
  本地一题完成，非法 proposal 不执行。真实 one-call prompt 与批量 publisher 尚待封存。
- `ch6_metrics.trace_cost`：以共同非负权重计价实际资源；未知资源不会补零。规划器的
  terminal estimate 不参与评分。正式测量权重和完整计量接线尚未冻结。

源码入口：`ch6_structures.py`、`ch6_sources.py`、`ch6_workload.py`、`ch6_local_runtime.py`、
`ch6_direct.py`；准备入口是 `fetch_ch6_development_sources.py`、`prepare_ch6_development.py`、
`extract_ch6_structures.py`、`check_ch6_development.py`、`prepare_ch6_pilot.py`。

38 项不重复的定向测试通过；审阅后又复核其中 8 项，不累计成 46 个独立测试。
本地 29 题均匹配独立 nested-loop/DFS reference，其中 **11 题为空答案**，全部保留。
首次本地 gate 因新 mapping 漏 version 被拒收，修复后单独记录 v2，未覆盖失败记录。
没有做 blanket regression、消融矩阵或付费模型试跑。

## Pilot 提案与预算

完整文件位于 `/Users/anthonyche/xgap-data/ch6-pilot-proposal-20260922-v1/`：
`inventory.json`、`pilot_manifest.json`、`budget_estimate.json`、`figure_registry.json`。
这是 **runnable=false** 的提案，不是已经冻结的启动 manifest。

主比较暂按每域每 W 层 24 个独立 pilot case、3 个方法、1 次运行：
`3 × 4 × 24 × 3 = 864` 次 NL 请求，模型调用上限暂按 864 次提出。
受控机制 pilot 每域每层先取 2 题，单因素扫描在默认点去重复用前为 1,800 次请求，
模型调用为 0。这不是正式样本量功效结论，正式 2,400 cases 的运行预算未冻结。

|量|当前提案/已知事实|
|---|---|
|NL output token ceiling|按每调用 4096 上限，合计 3,538,944；输入 token 尚未知|
|NL 时间敏感性|若每请求平均 5/15/60 秒，则串行约 1.2/3.6/14.4 小时；均为情景估计|
|Controlled 时间敏感性|若平均 1/5/15 秒，则约 0.5/2.5/7.5 小时；尚非实测|
|货币费用|API 价格未提供，保持 null|
|本地主机|Apple M2 Pro、16 GiB RAM，当前约 15.0 GB 可用磁盘；保留 6 GiB 底线|
|模型|已有配置精确 alias `qwen3.8-27b`；API 模式；未知服务 checkpoint/硬件不填写|
|图表|已登记 E1–E8、F1–F8、S1–S4、C1/T1；没有画虚构曲线|

现存 API profile 的 temperature=0、top_p=1、output cap=4096、timeout=60s、
disable_thinking=true 是核对到的旧冻结配置，并非新三域 prompt 已冻结；未自动代用 32B。

## 离正式 pilot 还缺什么

需要补齐：LC-QuAD 到 compact 的明确领域桥接和 FinBench query-card 审计；真实
模板多样性与 NL 固定条件核验；新 D1/D2 native materialization、真实 metadata/probe
目标和物理备选；LLM-direct 批量发布；共同计量/缓存/预算。当前 small cases 只做局部
开发验证，不能直接扩成正式测试来替代这些门槛。[roadmap](../roadmap.md)保留具体顺序。

原版 ARUQULA+FedUP 的已知 VALUES/OpTable 不支持仍按原样保留，没有改 baseline。
当前结果能说明方法停止合同和小图的编译/结果链路已得到验证，**不能说明联合方法
比 Two-stage 更快，也不能说明三个真实部署已具备正式比较条件**。
