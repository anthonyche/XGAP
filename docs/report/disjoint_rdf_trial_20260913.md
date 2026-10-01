# 共同 RDF 表示修正与真实验证 — 2026-09-13

共同输入修正完成。原版 FedX 使用原全局查询，现在返回66、9，与 XGAP 和独立参考
一致。此前128倍金额随重复规范事实的消除而消失，支持源表示重叠导致重复匹配的
诊断；它不构成 XGAP planner 优势。旧数据、旧8448/1152结果和 FedUP 聚合500均保留。

实现版本 `bc659f91dd9e124a3fccc257e278222c17f37fb0`。
[表示契约](../decisions/disjoint_rdf_metadata_v2.md)；
[审计记录](../../experiments/artifacts/disjoint_rdf_trial_20260913.json)。

## 改动和离线证据

- graph 文件完全不变；control 中24条重复类型/身份元数据使用显式的辅助命名空间。
  主体身份、字面值、真实控制属性、交易、金额和时间均不变。XGAP 每源编译映射识别
  本地别名；所有方法看到同样的两个端点，辅助元数据也纳入存储/装载/流量成本。
- 两源仍是211和36条 triples，交集从24变为0。新并集247条中去掉辅助元数据，
  恰好等于旧规范集合并集223条；全局公共词汇和三类金融查询没有修改。
- 4项新检查一次通过（0.57秒）：集合等价及三类独立答案、原模型/catalog和映射
  一致、字面值不被文本替换破坏、缺失元数据时拒绝发布。不重跑已接受的旧检查。
- 新 profile 指向实际装载文件的 hash，保留旧 materialization 作为来源记录。
  冻结模型权重不变，无训练、catalog重建或 graph复制。control序列化大小统计更新，
  迁移预测仍未校准；不宣称任何估计质量保证。

## 一次新真实边界

同一8实体/16关系小图、同一个已曝光的固定金融问题，每方法一次顶层调用。原请求和
reference文件的字节/hash不变，原FedX JAR不变。XGAP仅估计候选、执行一个最终计划。

| 方法 | 原始金额及独立评分 | 源请求 | 完整在线请求时间 |
| --- | --- | ---: | ---: |
| XGAP-RDF | 66、9；EM=1，bag F1=1 | 5 | 411.351 ms |
| FedX | 66.0、9.0；EM=1，bag F1=1 | 46 | 711.882 ms |

本轮所有源请求成功，恢复费用0。两源和FedX三个自有进程全部退出、代理已关闭。
源/profile准备1747.014ms，其中离线v2发布24.469ms；FedX服务就绪105.284ms单列，
惰性初始化仍包含在在线请求内。没有LLM、fit、probe、retry、baseline算法或查询修改；
没有重跑FedUP已知聚合错误，也未构建新summary。

这是顺序运行的一道开发题，启动/缓存顺序未平衡，**不从这两个时间计算方法提速或
总体效果**。零模型调用的原因是本轮只验证固定语义的输入和执行边界，不能当作外部
自然语言端到端实验。

## 实际验证入口及下一步

```bash
PYTHONPATH=src:tests /tmp/xgap-directed-tests.qU2YfW/venv/bin/python -m pytest -q tests/test_disjoint_rdf_profile.py
PYTHONPATH=src:tests /tmp/xgap-directed-tests.qU2YfW/venv/bin/python scripts/check_disjoint_rdf_trial.py --output-root /Users/anthonyche/xgap-data/disjoint-rdf-trial-20260913-v2
```

两个入口均首次通过。审计SHA-256：
`b5daef4e94814ce1c4fc7a941a3e650e2dc75622a86c1faab193ea496ecf94fc`。
原始响应、每个源请求、资源/计时和终态文件保存在上述结果目录。

接下来补共享NL前端到未绑定源地址的全局SPARQL编译，然后完成完整数据服务发布、
装载和平衡campaign。新表示的完整数据版本尚未发布，外部共享NL尚未实现，
`formal_campaign_ready=false`。120组及24/48/48划分不变；不改空答案分母或筛选好题。
Sep14 17:00核心/评价接口及Sep18真实实验目标保持，用户已恢复工作，继续推进。
