# 同请求模型动作、strong规划与执行

2026-09-14。当前为本地验收记录，真实服务门待执行。

新增[动作顺序契约](../decisions/acquisition_order_v1.md)：显式搜索优先级与耗时估计分开，
未知动作耗时及包含它的策略分数保持null。保留先可行、全声明AND分支和单最终计划。
新5节点9边冻结夹具含KNOWS/FOLLOWS两种真实关系；“熟人”槽位由模型提议，
身份、年龄下界、类型和来源由可信请求指定。只授权predicate未验证，不改硬约束。

8项新增检查+3项受影响检查通过（11 passed，1.04s）。同一普通请求中，受控
OpenAI-compatible响应进入strong工具后驱动实际进程内SPARQL查询：KNOWS得到Cara/e4，
FOLLOWS得到Zoe/e9；后者相对预设意图是错误答案，未被修复。多候选及非法返回走
预先构造的澄清后续；EXACT在提议后仍需验证；没有失败后续时不调用模型。
逆转显式优先级会直接澄清且零模型。未知动作成本不变成0、不取代已知分数的incumbent。

检查命令：

```bash
PYTHONPATH=src:tests:scripts /tmp/xgap-directed-tests.qU2YfW/venv/bin/python -m pytest -q tests/test_practical_model_e2e.py tests/test_strong_planning.py::test_bounded_improvement_can_replace_but_never_worsen_incumbent tests/test_practical_tools.py::test_frozen_catalog_runs_only_after_search_and_ambiguity_follows_declared_fallback
```

真实门计划仅一次请求：可信模板NL→live模型predicate提议→实际strong分支→一个最终
Neo4j/Fuseki计划。零fit/baseline/probe/retry；准备与服务启动离线计量。新fixture/snapshot
已离线冻结，runtime不构建catalog。声明澄清仅返回两种合法选择；文件故障为未建模
真实失败，不假装在强保证内。模型优先是被冻结的启发式顺序，未证明其延迟更低。

整体Goal未完成。北京时间9月15日02:00收尾总结、暂停，10:00恢复已写入Goal与调度。
