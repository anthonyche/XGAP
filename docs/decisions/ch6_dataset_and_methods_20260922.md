# 2026-09-22 数据与方法补充决定

用户提供的三份原文保持在 ch6_experiment_plan、query_structure_spec 和 coding_agent_brief
中；本文件记录其后获准的替代与实际接线，不改写原文或历史测量。

用户明确允许 D2 更换为可本地使用的数据源，并接受只发布脚本、不发布数据。
现采用 **MovieLens-derived 开发轨**：评分关系在 graph，电影类型属性在 control，
原 movieId/userId 有命名空间以避免不同实体类型碰撞。没有伪造 IMDb 演员关系或 Wikidata
映射。links.csv 的 IMDb/TMDB ID 只是映射候选，P345 一对一、缺失、冲突检查已实现；
尚未下载/验证 Wikidata 对应子集，当前结果不称 MovieLens–Wikidata。

|候选|条件与工程适配|本轮决定|
|---|---|---|
|MovieLens|官方研究许可，直接下载；评分/时间/类型适合计数、金额以外的数值聚合与联邦筛选|先接小开发包；正式候选为稳定 20M|
|TMDB|非商业 API 免费且需署名，须申请密钥，需冻结 API 内容|备选，当前不增加凭据依赖|
|IMDb TSV|本地使用仍受官方条款约束；仅不发布数据不等于所有使用都获准|暂不下载或装载，不宣称禁止所有学术用途|

来源：[MovieLens 开发包与许可](https://files.grouplens.org/datasets/movielens/ml-latest-small-README.html)、
[稳定 20M](https://grouplens.org/datasets/movielens/20m/)、
[TMDB FAQ](https://developer.themoviedb.org/docs/faq)、
[IMDb 使用条件](https://help.imdb.com/article/imdb/general-information/can-i-use-imdb-data-in-my-software/G5JTRESSHJBBHTGX)。

MovieLens latest-small 官方定位为 development，不能以它为正式研究成绩。
20M 尚未下载/转换；公开页面约 190 MB 压缩，原生/RDF 装载后的大小须实测。
MovieLens 不提供用户实名，不把 userId 改成真实人物；SUM(rating) 表示累计评分分值，
不称平均评分，也不是金融金额。二部图没有三边 cycle 或同类型 traversal，当前
D2 不强补这些结构。可以后续使用真实共享电影连接构造合法结构，需独立准入。

## 方法对齐

- XGAP 仍是一条 fixed-D、逐步观测后重规划的控制器。
- Two-stage：相同 slots/Lambda/epsilon、绑定动作、D/H 和完成保护；语义阶段只给获取成本
  评分，到资格成立的叶即停止这一阶段。按 candidate_id 字典序固定合格解释，不使用执行
  估价、gold 或便宜计划选含义；下一轮进入相同物理动作与执行。阶段切换不消耗虚构动作。
  仍保留全部一致候选供 loss 计算。编译失败不移除语义不确定性。
- 旧 sequential 全字段算法保留 `xgap-unified-sequential` ID；新方法是
  `xgap-unified-two-stage`。不能把两者历史结果合并。
- noProbe 只移除 probe 动作，保留 metadata 和同样的初始估计模型。
- shallow 是 D=1；正式发布时与 D 扫描相同 cell 复用，不重复计样本。
- myopic 只比较非终端动作即时估计成本，终端保留执行代价；资格、unknown 分支、资源
  预留和无进展保护不变。它仍可能选择便宜动作，但不能侵占已证明的完成路径资源。
- LLM-direct：一次完整 proposal，接相同物理组件，无澄清/修补/重试，也无意图资格保证。
  独立入口及本地执行检查已完成；专用批量发布、共享新 prompt 的封存尚未完成。

配置 v2 严格加载新字段，旧 v1 只补回历史默认值。方法/配置冲突在模型调用前拒绝。
实际 trace cost 通过独立 `ch6_metrics.trace_cost` 按实测资源计价；旧
`realized_trace_work_estimate` 保留为估价诊断，不能用作 F5/F7 的评分。

## 发布边界

本轮只授权并完成了本地准备。未调用付费模型，未启动新 Neo4j/Fuseki 服务或后台任务。
小数据的 RDFLib adapter 检查不能替代真实 Neo4j/Fuseki interface gate。原版外部方法
保持已记录 VALUES/OpTable 失败，不修改算法、不重跑填图。
