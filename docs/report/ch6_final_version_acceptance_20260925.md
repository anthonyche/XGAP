# 最终版本统一验收：D2 native + RDF 前缀

2026-09-25。用户已校验包并提交为 **3875163**。当前仅有提交回执，运行节点、
状态与终态尚待查询；不重复提交、不修改在途代码和预算。正式实验未启动。

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
存在时拒绝重提。没有代码 bundle，也不访问 GitHub。当前作业号为 3875163，节点待查。

服务器 journal：`/home/hxc859/xgap-ch6-artifacts/final-admission-4b80d3d-v1`。
日志：`final-admission-3875163.out`；预期归档：`/home/hxc859/xgap-final-admission-3875163.tar.gz`。
输出：`/home/hxc859/xgap-ch6-artifacts/formal-final-admission-4b80d3d-v1/D2`。

本地提交记录：`/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/final-admission-submission-3875163.json`。
已请求一次只读状态/日志回传；提交成功不等于验收完成。

## 剩余发布边界

本批完成后读取两份资格证书、源预算和真实运行节点；再绑定实际五方法执行单元、
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
