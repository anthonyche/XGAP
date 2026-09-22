# Query Structure and Workload Construction

本规范配套 [Chapter 6 plan](ch6_experiment_plan_20260922.md)。目标是构造可执行、可追溯、有独立答案的图查询，不是仅替换自然语言中的几个词。下面的 S01–S08 是本实验内部结构类别，不是 LC-QuAD 官方 template ID。

## 1. LC-QuAD 2.0 到底提取什么

**保留原始完整 SPARQL 作为来源证据，从中解析类型化参数模板；不能只保留匿名图拓扑。**

| 原始字段 | 保存用途 | 是否直接用于新 workload |
|---|---|---|
| `uid` | 追溯原始样本 | 是，作为 provenance，不作模板唯一键 |
| `template_id`, `template` | 原始模板标识与描述 | 是，另生成自己的规范化结构 ID |
| `sparql_wikidata` | 优先解析的原始查询 | 提取语义结构；不是直接向新数据执行的 query |
| `sparql_dbpedia18` | 对应 DBpedia 2018 查询（若存在） | 单独解析；不假定与 Wikidata 查询的三元组逐条相同 |
| `question`, `paraphrased_question`, `NNQT_question` | 语言表达与改写来源 | 可作措辞素材，必须核对改写后的固定约束与领域含义 |
| 额外字段（如 `subgraph`） | 原始版本的辅助分类 | 有则保存，缺失不杜撰；不替代 AST 分析 |

字段来自 [官方 JSON 说明](https://sda.tech/projects/lc-quad-2/)。下载文件时另保存 release/commit、文件 hash 和实际字段清单。

每条模板保留：

1. **结构**：有向 triple/path patterns、变量共享、连接键、变量/常量位置、类型限制。
2. **谓词**：比较运算符、FILTER 表达式树、数值/时间条件、字段类型。
3. **输出**：投影表达式、group keys、聚合函数、HAVING、DISTINCT、排序、LIMIT/OFFSET、空值及重复语义。
4. **参数域**：实体、关系、阈值、时间窗等可替换值及其类型；参数与数据匹配时的查询变量分开。
5. **执行划分**：逻辑源标识、跨源键、已核验映射及源快照；不把 endpoint URL 当语义源名。

不能把带聚合的查询缩成相同拓扑后视为同一个模板，也不能丢掉方向、重复语义或 tie-breaking。结构抽取使用 SPARQL parser，不通过正则删除 IRI。用确定性的变量重命名和结构编码去重，输出 `structure_hash`；无需求一般图同构或一般查询等价。

## 2. 支持范围与结构目录

第一轮以现有 compiler 的类型化查询语言为准，在同一份 allowlist 上接通下列结构。结构类别是设计目标；每个实际模板须通过两后端和独立 reference 的准入，不在纸面标为已经支持。

| ID | 图/输出结构 | 保留的关键语义 | 主要物理选择 |
|---|---|---|---|
| S01 | 单边匹配 + 属性筛选 + 投影 | 边方向、类型、常量、输出键 | 源端筛选、投影 |
| S02 | 两至三条边的 chain join | 中间变量共享、方向、连接条件 | 源内片段、join 顺序、bind/hash |
| S03 | 两至三条分支的 star join | 同一中心变量，多分支条件 | 哪一侧先筛选、跨源 key 传输 |
| S04 | 三边 cycle / 具有闭合约束的 join | 闭合键、必要的不等条件；不默认所有变量必须不同 | 片段切分、连接顺序 |
| S05 | 长度 1–3 的 bounded traversal | 允许重复边/顶点与否、长度、时间窗、路径内条件 | 原生路径或有限片段组合 |
| S06 | Group-by + COUNT + 可选 HAVING | COUNT(*)/COUNT(x)/DISTINCT 的区别 | 聚合位置、预过滤 |
| S07 | Group-by + SUM + 可选 HAVING | 计量字段、数值类型、edge identity、每组重复贡献 | join 前筛选、合法聚合下推 |
| S08 | 匹配或聚合结果上的 ORDER BY + LIMIT | 完整排序键、方向、确定性 tie-breaker | 源端 reduction 与最终 coordinator 输出 |

保留 S01–S04、S06–S08 中能从 LC-QuAD 实际抽出的模板；没有找到某类别时，在来源表中记为没有对应模板，不捏造 template ID。S05 的金融时间路径和 S07 的转账统计优先从 FinBench 读查询派生。其他结构由 SNB 官方读模板或明确标为 authored 的领域模板补足。

本轮不把任意 OPTIONAL、MINUS、NOT EXISTS、子查询、无限 `*` 路径、复杂 qualifier 展开自动纳入；它们进入拒收表，或先完成独立的编译/语义测试后发布新 allowlist。Wikidata statement/qualifier 模式不能随意压成一条属性边，除非转换规则明确保留其语义。查不到答案不代表语法不支持，二者分开。

结构类别与来源模板不同：例如 S02 内允许多个不同方向、返回变量和谓词位置的模板族。报告每个数据集各类别实际模板数，不声称 200 个参数实例等于 200 个新结构。

## 3. FinBench 的具体起点

从已核对的 [FinBench 查询规范](https://ldbcouncil.org/ldbc_finbench_docs/ldbc-finbench-specification.pdf) 选以下只读结构作为起点；正式实现核对固定版本的原始 query card，记录所有派生改动。

| 来源 | 派生用途 | 必须保留/明确修改的内容 |
|---|---|---|
| TSR 1（Exact account query） | S01 的单源控制和实体绑定 | 账户键及请求的属性 |
| TCR 1（Blocked medium related accounts） | S05 的有限转账路径与 RDF 侧媒介属性连接 | 路径长度、严格递增时间、窗口、输出和排序 |
| TCR 4（Three accounts in a transfer cycle） | S04/S07 的闭合连接及金额统计 | 三条边的连接关系、边贡献和聚合范围 |
| TCR 12（Transfer to company amount statistics） | S07/S08、跨源 case study | 公司账户身份、转账金额分组、时间条件和输出 |

不把加入风险注释、改变投影或去除官方截断后的查询仍称“原版 TCR 12”。派生查询有自己的 ID 和 `changes_from_source`。官方截断若保留，必须成为输出语义与 reference 的一部分；若本研究采用完整结果，则显式声明该派生版本取消截断并限制数据/请求预算，不能运行到一半截掉结果。

建议 D3 case study 的模板语义：指定 person/account、固定时间窗，取得关联账户向公司账户的转账，按公司累计金额，筛选金额阈值，再连接 RDF 中的公司注释。只有 RDF 注释选择率足以改变成本预测时才可能选择 probe；若不值得探测，直接执行也是合法结果。

RDF risk 若自建，必须用合成注释标识与生成 seed，不声称是真实公司的风险评估。若源数据只有 account 而没有可验证的 person 名称映射，NL 应使用 account，而不是把它改名为 Alice 并假定相同。

## 4. 同一结构落到三个领域

| 通用角色 | D1 SNB-derived | D2 IMDb–Wikidata | D3 FinBench-derived |
|---|---|---|---|
| 起点/实体参数 | person/message | person/title | person/account |
| 关系匹配 | knows、消息创建/回复 | 演员—作品、导演—作品 | owns、transfer、signIn 等固定规范关系 |
| 数值/时间筛选 | creationDate、消息长度等实际字段 | 年份、评分等实际字段 | 时间窗、amount |
| RDF 侧筛选 | 分区后的标签、地点/组织属性 | 核验映射后的类型、国家、奖项 | 公司/媒介属性或已标明的受控注释 |
| Group/aggregate | 消息/关系的计数 | 作品计数或已定义数值统计 | 转账计数、金额总和 |

表是角色映射，不是把任意金融结构硬套在 IMDb 上。每个领域只绑定确实存在且类型兼容的属性与关系。SUM 不能对类别标签执行。类似结构的不同领域查询是实验设计的覆盖，不是声称这些数据的语义相同。

每个主结构都至少提供一个确实读取两个源的版本；源结果在完整查询中的贡献须可检查。不能把空的 RDF 请求或读取后丢弃的 fragment 算跨源查询。

## 5. W1–W4 与歧义构造

从一个合法完整查询开始，指定固定字段、必须验证字段和允许暂未验证字段，构造部分表示与 NL。为每个未决字段注册明确候选域；完整候选是类型兼容且满足硬约束的组合，而不是任意字符串替换。

- W1：所有查询语义固定；计划能力或统计仍可能未知。
- W2：只隐藏实体身份，用自然名称歧义、明确标注的受控别名或同名候选；不重写原始身份。
- W3：跨源，隐藏实体和谓词/聚合含义，可含阈值等参数；例如“频繁”对应计数条件，而“总额较大”对应金额条件。NL 与候选域由独立核验保证相容。
- W4：在跨源请求中隐藏多个字段，可包括真正不同的逻辑数据范围。只有确实存在不同逻辑源/数据子集时才引入 source ambiguity；同一快照的 Neo4j/Fuseki 副本只是 physical placement，不产生不同 intent。

采用输出兼容的候选族；若可选聚合的类型或 schema 改变，将变化写进候选的完整输出合同，不用统一 F1 脚本假定输出结构不变。初始模型提议与注册模板不能访问 gold 以补齐遗漏字段。

主配置的三个字段等权，因此可达正损失是 1/3、2/3、1。u 沿用第四章的初始未绑定字段数，不是状态中尚未验证的字段数。u 扫描使用另一组预先声明的完整字段坐标与权重，从同一完整模板隐藏不同数量的字段，并保持候选数和结构匹配；不能每次重算 loss 分母制造“精度提升”。无法匹配的水平单列为 cohort 差异。

## 6. 信息动作与物理变化的验收

每个模板登记少量已命名的获取目标，不枚举全部谓词子集。

| 动作 | 实际请求例 | 应观察到的状态变化 | 不能发生的变化 |
|---|---|---|---|
| Binding | 请求未验证字段值/attestation | 记录验证并过滤不相容候选 | 模型自行给出验证 |
| Metadata | 请求指定 operator/接口的支持记录 | 相关物理备选的资格改变 | 未知当成支持；统计当作语义依据 |
| Probe | RDF 筛选 key 数、Neo4j 时间窗输入规模 | 估值/排名改变，候选语义不变 | 用试跑全部计划选择最快者 |
| Physical transform | 一个已检查的 pushdown/join/placement 变化 | 增加或替换有限物理备选 | 一次动作遍历全部 join orders |

每个跨源模板准备至少两个语义等价的物理备选或明确报告只有一个。预先保留高/低选择率以及信息不改变选择的 case，不以 XGAP 是否获益筛选。受控观测类别和代表值先冻结；真实响应进入 actual state，lookahead 的假想响应只进入临时分支。

至少检查一次“实际返回统计 → 缓存依赖键改变 → 某计划重新估价”的日志链。只有重新估价并不意味着计划一定切换；只有切换也不意味着实测总成本下降。

## 7. Builder pipeline 与文件合同

1. `intake`：下载/定位原始数据和规范，冻结版本、license、hash；不进入原始文件中改写字段。
2. `extract`：解析原始 SPARQL/query card，保存 AST、来源、支持/拒收原因。
3. `normalize`：变量重命名、参数类型化、结构去重；保存原操作语义。
4. `instantiate`：绑定领域谓词、实体和逻辑源，产生完整 queries；根据预先固定条件抽样，不调用被比较方法筛题。
5. `reference`：从冻结事实独立计算输出，验证源映射；可区分预先注册的 active-anchor cohort 与无条件抽样，不能混合后称自然分布。
6. `ambiguate`：构造 W1–W4 的部分请求、候选域和 NL；gold 单独存放。
7. `split-and-seal`：按模板族/来源分组，发布开发/测试清单及 hash；测试 query ID 在运行前冻结。

输出至少包括：

| 文件 | 内容 |
|---|---|
| `template_registry.jsonl` | source/version/uid、raw-query hash、原 template_id、structure_hash、S01–S08、AST、参数类型、支持状态和派生说明 |
| `dataset_manifest.json` | 原始与转换快照、实际规模、映射、源划分、许可及生成 seed |
| `public_cases.jsonl` | case ID、dataset/workload、NL、公开 schema/域、验证合同、快照和接口引用 |
| `controlled_states.jsonl` | 受控轨道的公共初始证据、完整候选族、合法动作及参考版本，不含 gold 标记 |
| `private_gold.jsonl` | intended query、各字段真实值、独立 reference ID；只供模拟用户与 evaluator |
| `references/` | typed rows、集合/多重集/顺序合同、reference 实现版本与 hash |
| `rejections.jsonl` | 所有解析失败、类型不兼容、缺少映射、模板不支持和原因 |
| `split_manifest.json` | template-family split、采样 seed、base case 数量和扫描派生关系 |

每个 case 的验收条件：来源可追溯；完整 query 类型正确；跨源映射有效；独立 reference 可重现；NL 与固定条件一致；候选族不同且合法；gold 对在线模块隔离；每个指定 source 对输出语义有作用；所有参数变体保留 parent case ID。

第一批交付建议是 **每个领域 8–12 个开发模板实例**，覆盖简单、join、聚合、有限路径及其真实支持范围。它们用于编译/reference/接口验收，不用于宣称准确率或规模性能。通过后才按 Chapter 6 plan 扩展到 pilot 和正式目标。
