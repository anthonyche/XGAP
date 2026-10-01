# 修复后共同输入：48 题五方法完整链路评价

2026-09-26，用户明确授权：冻结修复后的共同输入，运行 48 题、五方法完整链路评价。
本轮接续已通过的[八结构真实入口验收](../report/ch6_entry8_acceptance_20260926.md)，
一次提交、无自动重试，不再先要求所有方法或所有问题成功。

## 冻结范围

保持旧 3886776 的 48 个 case ID：D1/D2/D3 各16题，每域 W1–W4 各4题；每个 W
包含 uniform/native、active/native、uniform/RDF、active/RDF。保留原选择规则和暴露
历史，原参考答案、scope、controlled query、私有 query/nonce、完整源快照和后端配置
不变。不能把这些已用于开发诊断的题目声称为新的独立测试集。

所有五方法获得同一份新公开问句，只追加由公开 domain/template/scope 决定的边角色
说明。私有用户文件只更新 question hash，保持原 query/nonce；它不会提供公共文字。
四内部方法使用 `frozen_compact_model_public_contract_v1`，把已经验证的公共约束
叠加到真实 serving profile；源端点、存储和资源参数保持原样。TS 使用原 profile、
原算法、原 JAR、原预算及重试规则，不改它生成的 SPARQL。

旧 backend admission 只证明原结构化 query/source/reference。新入口通过显式迁移证书
验证所有允许变动后复用该证据，不能把它冒充新自然语言提议或答案的运行成功。
在线 worker 不接收迁移证书或额外 private 文件；权威信息仍经付费模拟用户接口获取。

| 方法 | 本轮请求 | 支持边界 |
|---|---:|---|
| XGAP | 48 | native + RDF，按信息价值选择真实 probe |
| NP | 48 | 同配置，仅禁用 probe |
| SH | 48 | 原冻结方法配置 |
| GR | 48 | 原冻结方法配置 |
| TS | 24 | RDF；另24个 native 位置明确不支持 |

合计216个适用请求，一轮，D1→D3→D2。预算继承原合同：8 CPU/24 GiB，不固定节点，
不申请 GPU；主批次6小时、Slurm6:15。模型调用上限1728；输入/输出 token 停止阈值
600万/100万，认证调用单列；160 GiB 存储停止上界加6 GiB安全余量。原逐题预算不变。
XGAP/NP 的声明成本模型与先验保持原冻结值，不强制购买 probe 或预设收益。

## 已完成验证与运行交接

- 本地原48题迁移后仍为三域各16题、W各12题、uniform/active各24题，无重采样。
- 六个真实源 profile 的公共证明及 serving overlay 通过无服务核验；动态端点及
  原 profile 不变。该检查不运行 source session、模型或答案查询。
- 新 manifest 显式 pin `entry_migration` 和 `entry_profile`，缺一或未证明变更即拒绝。
- 失败证据自动归档：只读已封存 source/federation/lookup 的失败查询及响应前缀，
  单响应最多256 KiB、总额32 MiB，排除模型请求、headers 和 credentials。缺失与截断
  单独记录，不更改方法结果，也不触发重试。
- 本轮 SSH 和浏览器控制均超时。精确版本提交及包校验后交接，尚无新作业号。

迁移预览：`/Users/anthonyche/xgap-data/outputs/xgap-small48-migration-20260926-v1/selection.json`
SHA `8850e6144ee74b26200555290f8b3585a0c7b4b7fb728ffc648e8b291c125924`。
六源接线：`/Users/anthonyche/xgap-data/outputs/xgap-small48-migration-serving-check-20260926-v1/receipt.json`
SHA `11007d4ff25f64bb27d4b28f4a6b56ffd5397a1b4f04efde8bbab7be16eae5d6`。
服务器使用原路径与精确版本重新生成、校验发布 pin；本地镜像预览不是可执行发布包。

## 结果交付

运行包自动生成逐请求与分组 CSV、用量账本、失败分类、support 表及原始证据索引。
分组报告 E2E、planning/execution、模型调用/token、probe/source calls、传输字节、CPU/RSS、
答案正确性与覆盖，保留失败/截断的分母。不以快速拒绝当作快速回答。
这是一组真实48题结果；候选数、深度、源数、图规模和并行的因子实验仍需各自运行。
旧结果和 mockup 独立保存，不回填或合并。整体 Goal 尚未完成。
