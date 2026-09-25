# 最终版本统一验收：D2 native + RDF 前缀

2026-09-25。**3875163 原始证据验收完成**：归档 SHA、1,075 个文件及 845 个可用
pin 核对通过。两份部署资格证书从原始答案、独立参考、预算及关闭记录重算一致。
同一查询代码 4b80d3d 下，native 24 correct；RDF 29 correct + 3 source_timeout。
全部 56 个冻结输入覆盖，两个部署 `eligible_for_evaluation=true`。
不重提、不重跑；正式实验未启动，`formal_campaign_ready=false` 保持原义。

## 已验收的终态与证据

| 部署 | 本次日志报告 | 合并已有证据后的覆盖 |
| --- | --- | --- |
| native | complete=true，24 correct，remaining=[] | 同 4b80d3d 原 24 题 |
| RDF | complete=true，5 correct，remaining=[] | 加上 3874144 的 24 correct + 3 source_timeout，共原 32 题 |

native 资格证书 SHA-256：`8be76bc1e3b2d74d817d6a7be124388f0fb15f2fc72008aafcbf9e1e765e6480`。
RDF 资格证书 SHA-256：`e83e0af9172f50002a4da58ac17b6729b2e3445476391ab6f8e2fbe2fba24669`。
回传归档 `/home/hxc859/xgap-final-admission-3875163.tar.gz`，1,708,871 B，SHA-256：
`6a33f25c8115961b27fbeac044659db8710f9666603daa700ffc7e1c625799b4`。

已校验归档、全部冻结输入、实际计划/有序答案、源关闭和两份证书的原始证据重算。
RDF 三个旧超时保留，不为获得全正确而重试或从分母中删除。
compt317 的 21:04 是整个作业时长，含离线服务准备和证据封存；不能当作查询延迟，
也不能与此前 compt304/compt311 的作业时长混算提速。
终态交接已独立保存为本地 `final-admission-terminal-user-report-3875163.json`，
不覆盖原提交记录。

| 部署 | uniform | active-anchor | 正确空答案 / 非空答案 |
| --- | --- | --- | --- |
| native | 12 correct | 12 correct | 17 / 7 |
| RDF（含保留批） | 15 correct + 1 timeout | 14 correct + 2 timeout | 19 / 10 |

本次新增 native 24 题共 59 次后端请求、1,569,825 B 响应；worker 中位数 9.798 s，
范围 7.608–54.831 s，合计 304.070 s。新增 RDF 五题共 21 次请求、61,936,025 B，
worker 中位数 13.314 s，范围 11.224–39.801 s，合计 103.576 s。
这些是确定性 gold-query 后端诊断，不含 NL 解释和在线信息策略，不作为五方法端到端结果。
native 三段离线服务准备合计 332.726 s，RDF 新段 359.027 s，分别报告。

方法/源的本次最大采样 RSS：native 47,951,872 / 1,428,836,352 B；
RDF 316,551,168 / 1,228,247,040 B。采样 RSS 不是精确峰值，也不是 OS 强制上限。
四个新段及六个保留段均核验进程回收、观察器停止和服务副本删除；新段零模型调用、
29 次最终计划执行，所有实际计划匹配运行前冻结选择。没有观察答案后再择优计划。

[逐题审计表](data/d2_final_version_admission_3875163.csv) 保留部署和作业来源；
RDF 旧批来自 compt304，不与新 compt317 数据合并成同环境提速结论。
本地审计：`/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/final-admission-audit-3875163.json`。

## 补齐的证据

`xgap-native-prefix-inputs-final-v1.tar.gz` 共 5,532 B，SHA-256
`24b75648e9d07d1e9b1cf9c92c4eb48a8fc379d8c199eff90475fe5855e27604`。
四题各五个文件，共 20 个原始输入 pin 均匹配冻结 native bundle；未修改输入。
本次只为原索引 0–3 生成 symbolic plan，其余 52 个比较复用已完成记录。
全部 24 native 和 32 RDF 的选择现已可核对，零数据库/模型调用。

native 19/24 的当前计划不同于各自早期实际执行版本；另 5 个相同。
相较 c3437fc 的统一静态选择，18/24 不同，主要是已批准的过滤后绑定键域接线。
这些不是 19 个新 bug；旧成功证据保留，但不当作改变后计划的实际执行结果。
本次 census 的 RDF 27 个实际计划全部与当前选择相同。

## 一次验收的范围

| 部署 | 本次执行 | 保留证据 | 目的 |
| --- | --- | --- | --- |
| native | 原 24 题完整顺序，一题一个最终计划 | 历史成功/失败均保留 | 19 个改变后的计划需要实际验收；5 个未改变计划作为一次完整部署一致性检查 |
| RDF | 仅原索引 0–4，共 5 题 | 3874144 的原索引 5–31：24 correct + 3 timeout，全部复用 | 与已有 27 题形成同源码、同预算的完整 32 题证据 |

现有后端可评价合同要求同一诊断源码覆盖完整 bundle。为避免引入新的跨版本
证明框架，只做这一次最终冻结版本验收；不逐题调参，不通过试跑选择物理计划。
RDF 已完成的 27 题（含三个超时）不再执行。这里最多 29 次最终计划，不是五方法
NL 矩阵，也不是全量正式实验。

若所有证据满足合同，程序直接生成 native 和 RDF 的 `backend-eligibility.json`；
后者从新前缀和保留的六段 census 原始回执重新计算。允许已声明资源截断，
`eligible_for_evaluation` 不等于 `all_answers_correct`，仍不宣称正式全量 ready。
未知错误、答案不一致或关闭不全停止，不自动重试。

## 冻结配置

- 执行 checkout：现有干净 `XGAP-4b80d3d`，精确
  `4b80d3d128e57752dd5ef8dd845bc2d1eea9eb0a`；不改服务器代码。
- native 既有 v3 estimator/profile 与完整 prepared stores；RDF 既有 Direct/lazy
  runtime、原 estimator/profile 和完整源。数据、题目、参考、排序及预算均不变。
- 每请求 60 s，每 worker 120 s，方法/源观察内存 3/4 GiB，源启动上限 1,800 s。
  每段最多 8 题；只有核验关闭后才能接续。启动独立计量，无预热查询。
- CPU batch：8 核、24 GiB、03:15:00、不绑定单一节点、no-requeue、不申请 GPU。
  native/RDF census 调度上限分别 2/1 小时；这些是上限而非预计耗时。
- 两个部署的待执行计划在任何后端启动前全部核对并封存。实际 worker 计划再次
  对照冻结 SHA；变化则停止。
- 资格审核器作为只读 sidecar，逐字节来自 `12f7a34` 的已测试模块。
  4b80d3d 到该版本的差异仅在发布/图绑定检查；source-runtime 脚本的函数级差异
  只有 `validate_admission`，planner/compiler/executor/estimator 与诊断入口未变。
  不把 sidecar 所在版本冒充实际查询执行版本。

## 包与本地验证

`/Users/anthonyche/Downloads/xgapfinal-admission-4b80d3d-v1.zip`，13,105 B。

SHA-256：`69fed3f9706ec3086d5b71585814b0f4cbe386a219b51b15a4a3f2fd1fe03d70`。

本地校验覆盖 56 题的真实冻结输入、既有 27 题回执/计划、原 profile/估计器、
包成员 SHA、Python 3.6 stage 语法及 Slurm shell 语法。预算变化、native 缩减、
重复 RDF 后缀、错误 commit、伪造旧回执五类异常均在提交前拒绝。
没有调用数据库或 LLM，没有重跑回归套件。

本地工作目录：`/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/final-admission-pack-4b80d3d-v1`。
只读比较：`final-prefix-selection-12f7a34-v1/receipt.json` 与
`final-selection-reconciliation-83d972f-v3/receipt.json`。

## 服务器交接

以下提交已由用户完成，保留作复现记录，**不要再次执行**：

```bash
python3 -c 'from pathlib import Path; import hashlib,zipfile; p=Path("/home/hxc859/xgapfinal-admission-4b80d3d-v1.zip"); assert hashlib.sha256(p.read_bytes()).hexdigest()=="69fed3f9706ec3086d5b71585814b0f4cbe386a219b51b15a4a3f2fd1fe03d70"; exec(compile(zipfile.ZipFile(str(p)).read("stage.py"),"stage.py","exec"))'
```

stage 先核验全部输入与既有 checkout，再创建唯一提交记录；旧 journal/output
存在时拒绝重提。没有代码 bundle，也不访问 GitHub。作业号为 3875163，节点 compt317。

服务器 journal：`/home/hxc859/xgap-ch6-artifacts/final-admission-4b80d3d-v1`。
日志：`final-admission-3875163.out`；已生成归档：`/home/hxc859/xgap-final-admission-3875163.tar.gz`。
输出：`/home/hxc859/xgap-ch6-artifacts/formal-final-admission-4b80d3d-v1/D2`。

本地提交记录：`/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/final-admission-submission-3875163.json`。
状态、日志和归档均已回传、核验；无需再执行本批准入查询。

## 剩余发布边界

两份资格证书、源预算和真实运行节点已核实。接下来绑定实际五方法执行单元、
D1/D3 与正式因子输入、F6 固定池和全局 API/token/墙钟预算。先一个数据集的运行
入口也须通过发布检查；不将本批准入成功当作整套 21 图矩阵已准备完整。

### 等待期间已核对的材料

本地只读复核 `xgap-release-audit-20260924.tar.gz` 中 1,231 个文件与现有副本，
并沿相关材料验证 190 个可用文件 pin；2,201 个引用不在这份有意裁剪的归档中，
不能据此认定服务器缺文件。本次零模型、零后端调用、零作业提交。
这是归档材料核对，不是对当前服务器状态或查询正确性的重新验收。

| 材料 | 已存在的证据 | 发布前仍需完成 |
| --- | --- | --- |
| D1、D3 正式 NL 输入清单 | D1 RDF/native 为 32/24 题，D3 为 32/32 题；四份清单各准备 3 次重复，RDF 含五方法、native 明示 TS 不支持 | 清单版本为 7058d24；更新最终配置、输入 pin、支持合同及资格证据。重复数尚非最终全局预算冻结 |
| D1、D3 后端 | 四个部署均有 8 题 pilot 成功回执 | pilot 不能冒充最终版本 test 全覆盖；对照最终发布入口补齐必要证据 |
| N/u 实际因子 | 28 个实例及旧版后端成功回执，覆盖正式 N/u 水平 | 绑定当前执行单元与对应资格，保留原实例和参考 |
| 源数、规模 | 2/4/8 源、0.25/1/4 倍六份实际部署，每份两种锚点分层均有成功回执 | 绑定最终 source/runtime/预算合同；不重新造数据或按结果筛选 |
| F6 | 已有节点本地、源内存 4 GiB 的固定池实测与成本核验 | 旧 D1/D3 清单为源内存 8 GiB，不能直接绑定该实测；生成配置一致的新清单后核对 |
| 探测价格轴 | 旧执行单元明确 `probe_axis_active=false` | 如无真实已注册的探测动作，保留固定参考并说明参数不生效；不得人为增加探测制造 NP 差异 |

本地审计：`/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/release-materials-audit-20260925-v1.json`。
正式发布仍需最终支持范围、样本数、全局 API/token/墙钟预算和 21 图单元绑定。
这些工作不能用一句“3875163 成功”代替，也不要求先优化掉所有合法超时。

## 零查询发布准备：服务器报告成功，原始归档待验收

包：`/Users/anthonyche/Downloads/xgapreleaseprep-cfb9f6d-v1.zip`，55,863 B，SHA-256：
`df9bacbd3b51e296928b10232bd5624f1914d0788c8ec53e379ea808db5df741`。
执行前部署独立 publisher checkout `cfb9f6de9ede80693eb73fc04056654f3cd94bb1`。
与实际查询版本 4b80d3d 的六个源码差异仅为发布检查；共享 source-runtime 的函数
差异只有 `validate_admission`。planner/compiler/executor/estimator 没有改变。

该包不提交 Slurm、不启动服务、不调用模型、不运行答案查询、不重测 F6：

- 重算已验收的 D2 证书，绑定 3/4 GiB 方法/源内存、60 s 单请求和原 128 次源请求额度。
  NL worker 暂沿现有 300 s、D=2、H=12、epsilon=1/3 的准备配置。
- 原 56 题全保留。XGAP/NP/SH/GR 各支持 56，TS 支持 32 道 RDF、24 道 native 明示不支持。
  三个 RDF 超时仍处于五方法支持分母，不能按诊断结果筛题。
- 沿旧准备清单生成三次重复：每次 native 96、RDF 160 个 cell，合计 768 个待运行请求。
  **这是准备清单数量，不是执行次数或最终全局预算批准。**
- TS 复用已准入 Linux 原实现/预算，只引用该共同 RDF 源已有公共 metadata；不改提示、
  搜索、模型或答案，不改源事实。上机核验其真实依赖文件和作者 checkout。
- 收集 D1/D3、因子和外部运行环境的缺失小型元数据，单文件 8 MiB、总量 64 MiB；
  不复制图存储，不读取凭据，不覆盖旧材料。

本地对真实 native 24 题已验证三份清单共 288 个 cell；RDF 完整证书和共享运行配置
校验通过，支持合同 56 题/五方法分母核对通过。增加查询/模型/作业、缩小病例、改变
深度均被包合同拒绝；零数据库和模型调用。以上为本地验证；实际服务器回执如下。

用户随后执行该包，服务器最终 JSON 报告 `success=true`、`error=null`。
代码已部署到独立 `XGAP-publish-cfb9f6d`，并生成 native/RDF 各三份清单：

| 部署 | 独立题目 | 每轮可运行方法项 | 重复数 | 待运行总项 |
| --- | ---: | ---: | ---: | ---: |
| Native | 24 | 96 | 3 | 288 |
| RDF | 32 | 160 | 3 | 480 |

支持合同报告 XGAP/NP/SH/GR 各支持 56 题；TS 支持 32 道 RDF，24 道 native
标记 `unsupported_deployment`。两份执行单元均 `probe_axis_active=false`，
不得据此声称已有探测策略收益。768 为准备项数，不是已执行实验数。

服务器回执另报告收集 2,475 个文件、略过 2,229 项。采集器有文件类型/目录/容量边界，
这些略过项不直接等价于实验缺失；取得采集明细后逐类检查。
`backend_calls=model_calls=submitted_jobs=0`，`formal_campaign_ready=false`。
不需要重提包或查询作业。

原始归档：`/home/hxc859/xgap-releaseprep-cfb9f6d-v1.tar.gz`，2,439,163 B，
SHA-256：`36d2c6880bed7ee8a5e23dcc706c41bc5bf805779f174c3ccd95c8e64816e22c`。
当前证据层级为**用户提供的服务器终端回执**，原始归档尚未下载验收。
下一步核对归档哈希、六份清单与支持合同、实际外部依赖核验记录，
并补齐收取的 D1/D3 与因子材料、统一预算及图绑定。

全局发布审计通过前，不提供全量执行指令。D1/D3 当前资格、21 图绑定、最终样本数
和 API/token/墙钟总预算仍是独立收尾项。
