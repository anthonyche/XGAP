# 外部对照核实：方法存在、接口匹配与本地可运行分开记录

核实日期：2026-09-12。范围是当前实验方案的定向检索，不是完整系统综述，也不证明
名单覆盖截至今天的所有SOTA。以下来源是论文作者、会议、项目官方实现或官方文档。
提案阶段只做来源核实；用户批准后已获取FedUP源码并构建FedX薄适配，见下方更新。
没有下载模型/大数据、训练或执行查询。

| 外部方法 | 已核实的事实及直接来源 | 对XGAP实验的适用性判断 | 当前本地状态 |
|---|---|---|---|
| FedUP | WWW2024工作，官方提供SPARQL联邦计划、summary构建与FedX/Jena执行路径；运行期source selection可能发ASK。[官方实现](https://github.com/GDD-Nantes/fedup) | 主要现代联邦对照。固定RDF源和相同查询；summary属离线一次性成本，运行期ASK不能免费。它不原生接受Cypher或NL。 | 后续已锁定commit并获取源码；未构建/查询，见接入记录。 |
| FedX / RDF4J | 官方文档提供SPARQL endpoint federation和查询执行配置。[官方文档](https://rdf4j.org/documentation/programming/federation/) | 成熟而强的联邦对照；与FedUP固定相同RDF4J/FedX执行版本，可分辨上层规划与执行差异。不是以年份称其最新SOTA。 | 后续薄适配已编译，固定5.1.2；未执行查询，见接入记录。 |
| Comunica | 官方支持多源SPARQL查询。[联邦文档](https://comunica.dev/docs/query/advanced/federation/) | 可增加独立实现对照；优先级在FedUP/FedX之后。不要以它替换失败的既定方法后隐藏失败。 | 文档可读，未集成。 |
| KBQA-R1 | 作者论文v4于2026-06-22更新；ICML2026目录列出该题名。作者提供GrailQA/WebQSP权重入口和Freebase执行要求。[论文](https://arxiv.org/abs/2512.10999v4)、[会议目录](https://icml.cc/Downloads/2026)、[代码](https://github.com/sunxin000/KBQA-R1)、[权重卡](https://huggingface.co/unixin/kbqa-r1) | 应优先纳入当前KBQA前沿候选；使用作者权重的系统比较须披露训练与模型差异。把它改用现有Qwen不能称官方复现。 | 权重页面存在；未下载/核验/部署。不能由“LLM HTTP已可用”推断此模型已可服务。 |
| KBQA-o1 | ICML2025论文描述MCTS与策略/奖励模型的agentic KBQA。[会议论文](https://proceedings.mlr.press/v267/luo25d.html)、[官方代码](https://github.com/LHRLAB/KBQA-o1) | 有价值的搜索型对照；真实使用的模型、训练产物、工具调用与总时间均须计入/披露。不能直接搬其论文整榜F1与XGAP小样本相比。 | 未复现。代码文档含训练步骤；现成可用checkpoint尚未核实。本周不自动启动其完整训练流程。 |

这些“适用性判断”是我们的实验设计推论，不是上述来源已经证明XGAP可胜过它们。
KBQA-R1会议目录可读，单独poster页抓取失败；论文版本及作者仓库共同支撑其身份，
不把poster抓取失败推断成论文不存在。四个仓库的公开commit API本地请求均URLError，
首次提案阶段因此未填写猜测SHA。用户批准后的Git读取固定了FedUP commit，显式使用
系统已有代理后源码获取和FedX构建成功；原失败保留，详见
[后续接入证据](external_federation_preparation_20260912.md)。网页可读与实际构建是不同证据。

## 数据artifact与可比性

- **FinBench** 是金融场景图数据库benchmark，官方交易负载包含读写；不是现成的
  自然语言问答集。[官方介绍](https://ldbcouncil.org/benchmarks/finbench/)。我们当前
  read-only、异构分区和NL问句是明确标注的衍生工作负载。不能称完整官方合规结果。
- 当前已有的SF0.1归档是66,710,298bytes，SHA
  `f0359b5c4515cd5d86349b4a11a7470f6f153e42c5ac21c59e70f5c0d0b37a60`。
  [本地验收记录](finbench_original_three_native_20260911.md)明确18张snapshot表、
  365,181行；这些不是简单的|V|/|E|。公开SURF目录同名SF文件显示不同压缩大小，
  因而不能把该目录的归档或别的版本统计直接当本地相同字节。[SURF记录](https://repository.surfsara.nl/datasets/cwi/ldbc-finbench)。
- **FedShop** 有官方数据/查询生成器与source assignment参考；官方mini教程是20/40
  endpoints、12模板的24次实例化。[官方仓库](https://github.com/GDD-Nantes/FedShop)、
  [mini教程](https://github.com/GDD-Nantes/FedShop/wiki/1.-Quick-start)。本提案中的
  2/4/8源配置是拟议的FedShop-derived有界子轨，不能换名成官方mini或官方整榜。
  reference source assignment只能用于独立检查，不能单独作为XGAP的输入优势。
- **GrailQA** 的旧冻结150题和曝光标签保留；当前持久Freebase事实证据仅1/964分片，
  不能将缺事实导致的失败归为模型能力，也不能用gold答案补齐推理图。
  [现有事实证据](entity_answer_evaluation_20260911.md)。KBQA对照要求相同可执行KB
  事实范围；完整KB服务可用性和作者权重部署仍待完成，不用toy替代后声称完成此轨。

## 三种比较分别能说明什么

1. **RDF同环境、固定语义查询**：XGAP-RDF、FedUP、FedX同源同资源、独立等价输入。
   用于规划/执行效率与规模；没有模型调用，不能充当NL端到端结果。
2. **RDF同环境、NL端到端**：XGAP两模式与“共享NL前端 + FedUP/FedX”组合方法。
   每个系统计入自己的完整在线推理成本。后者必须标为组合baseline，不能写成
   FedUP论文自带NL能力。独立固定解释轨仍用于隔离前端与后端影响。
3. **异构原生及KBQA外部系统**：Neo4j+Fuseki的XGAP原生结果单独分面；RDF迁移基线
   在相同逻辑事实的冻结镜像上执行，报告镜像的一次性成本，不能把差异全部归因
   于planner。GrailQA上的作者KBQA模型按其真实配置比较，不假装模型/训练相同。

这三种范围不能混成一个“统一提速倍数”。某方法没有可比较的指标或未完成接入时，
显示未测/范围不适用，不填0，不把内部变体改名为外部SOTA。
