# 同请求模型动作、strong规划与执行

2026-09-14。实现提交`57ed970`；本地门和一次真实服务整体门均通过。

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

真实门只执行了一次普通请求：可信模板NL→live模型predicate提议→实际strong分支→一个
最终Neo4j/Fuseki计划。模型选择KNOWS，实际结果Cara/e4与事先编写的gold一致。

|测量项|本次观察|
|---|---:|
|在线query-to-answer|812.198 ms|
|strong搜索 / 首个可行策略|46.093 / 46.091 ms|
|信息获取（含模型适配开销）|497.617 ms|
|最终联邦执行|259.400 ms|
|实际模型调用 / tokens|1 / 353输入+19输出=372|
|最终计划 / 源请求|1 / 2（Neo4j、Fuseki各1）|
|澄清调用|0|
|展开状态 / 符号动作 / 编译状态|9 / 3 / 4|
|实际gold / 答案|1行 / 完全一致|

模型两个候选、无结果和失败的四个分支都在返回的策略中；无结果/失败各有两答案澄清
后续。预先symbolic preflight与实际请求生成的policy完全相同，搜索期0外部调用。
运行只取KNOWS那条分支，未执行其他意义的查询。模型选择仍是未验证predicate，
EXACT的权威要求没有被这次正确答案替代。

服务启动7350.184ms、tiny加载285.578ms单列为准备成本，未混入812ms在线请求。
两服务收尾均成功，Neo4j退出0、Fuseki退出143；主实验句柄54250退出0。
零fit/baseline/probe/retry；新fixture/snapshot已离线冻结，runtime不构建catalog。

[证据索引](../../experiments/artifacts/practical_model_e2e_20260914.json)，
[原始receipt](/Users/anthonyche/xgap-data/practical-model-strong-native-20260914-v1/receipt.json)，
[完整结果/策略/轨迹](/Users/anthonyche/xgap-data/practical-model-strong-native-20260914-v1/result.json)。

这证明新的live信息动作、strong规划和双引擎在同请求连通。它仍是可信有限模板的一槽
模型提议，不证明任意NL结构验证、一般准确率、模式速度优势或论文总体结论。声明澄清
仅返回两种合法选择；文件故障为未建模真实失败，不假装在强保证内。模型优先是冻结
的启发式顺序，未证明其延迟低于本地澄清；本次估计器缺失，使用可行物理fallback。

下一项是把EXACT/PERFORMANCE、预算、工具顺序和冻结估计器的配置对齐到可发布的普通
请求入口，再按研究协议验证成本/排序；不能把当前Python夹具配置直接冒充论文模式。

整体Goal未完成。北京时间9月15日02:00收尾总结、暂停，10:00恢复已写入Goal与调度。
