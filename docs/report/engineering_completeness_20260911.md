# XGAP 工程完整性核对：2026-09-11

后续用户明确：XGAP是research prototype，以论文实验结果为核心，不追求完美。
因此下文的“尚未实现扩展”不自动成为实验版的阻塞项；以拟报告的研究范围判断
必要性。T3-B随后补充了通用入口的执行观测memory复用（见同日memory报告），
更广adaptive能力仍按其实际入口区分。下文保留约16:00核对时的状态。

按北京时间约16:00的实际代码、调用链和验收记录核对。当前T3-A在73575c7基础上
已通过完整回归3457/38及24个入口。本报告与该验收版本一并保存，不把测试数量折算为完成率。

结论：有限查询语义下的确定性执行骨干已经实现，并有真实Neo4j/Fuseki证据；
原始设计中的完整agentic系统尚未全部收口。剩余工作包含实际集成缺口、尚未实现
的系统能力，以及代码已存在但缺真实验证三种，不能统称为“功能没做”。

## 已实现与验证层级

| 能力 | 实现状态 | 已有验证与实际剩余 |
|---|---|---|
| 语义表示与算子 | 已实现有限profile的九种semantic DAG算子、路径及typed binding规则 | 有独立gold、模块测试和真实双库案例；不承诺所有任意组合或范围外语言 |
| 编译、联邦执行、结果归一 | 已实现Cypher/SPARQL编译、插件、调度、coordinator join/align/aggregate等 | 真双库及必须跨库的split-data slice已经运行；大规模表现仍待评价 |
| 目录、绑定与可选ontology | 离线publisher与只读FrozenResolutionBundle已实现并接入新入口 | 小图冻结/读取/绑定已通过；既有真实数据格式接入新bundle仍需适配 |
| NL Interpretation和LLM接口 | provider接口、真实HTTP适配、结构验证、token预算、错误/usage记录已实现并接线 | HTTP契约及受控响应回放已验证；Qwen实际服务、真实输出正确率及其小图执行尚未验证 |
| 物理计划选择 | 显式source/replica声明、候选枚举、观测、成本选择与静态无观测对照已接入新入口 | 同意义候选与真实答案验证已通过；默认模型的校准/实际收益未证明 |
| memory和自适应重规划 | MemoryStore、PlanSnapshotMemory、AdaptiveFederatedExecutor及专用runner已实现 | 有历史专用真双库验证；新run_question链未自动调用这些模块 |
| 实验对照与消融 | 专用runner已有static、no-memory、no-profile/probe、no-replan、full-agent等 | 历史机制/实验记录存在；不能当作本周新模型/新链路的结果 |
| 失败记录/回放 | Interpretation响应和失败可保存并零外部调用回放；runtime留终态与调用记录 | 通用backend任意失败的独立回放不是已完成能力；已有最小回放继续用于debug |
| 远程作业 | 精确版本部署、Slurm提交/查询/取artifact/取消的工具接口与脚本存在 | 当前人工通道完成实际提交；浏览器控制不可用是访问障碍，不是缺少整个remote模块 |
| 轻量UI | 本地澄清、状态及提交预览界面已存在 | 面向较早专用session；通用问题入口的完整UI接线未完成，UI保持后移 |

`run_question`当前确实调用Interpretation，然后调用固定目录绑定、规划和执行；
不是只有一组彼此独立的测试函数。实际模型provider可以传入这个入口。为了在
当前GPU分配条件下验证，远程先生成五题记录，再送回同一原生小图执行；这一
传输分阶段验证不能冒充共址的全链路性能测量。

## 真正未完成的工程部分

1. **现有agent能力在新主入口的集成。** 当前普通执行路径是选择性绑定之后，
   一次枚举、观测/选择、执行，再返回终态。memory更新、跨query复用、执行中
   重规划及相应消融主要在专用runner；不是所有通用query已经自然享有这些能力。
   这是调用链/状态传递的实现工作，单纯多跑测试不会把它接起来。
2. **真实数据到新入口的适配。** FinBench/Freebase已有数据与执行工具；新的
   `run_question`直接消费者目前主要是toy。需要把选定真实样本的schema、identity、
   source、冻结catalog和问题协议接入同一边界。不能说整个数据管线尚未实现，
   也不必重写所有legacy runner后才开始评价。
3. **通用运行资源管理。** 当前调度器返回和物化完整中间行，没有通用streaming、
   全局中间行/内存上限或贯穿backend的查询级取消。已有请求timeout、有限调用
   预算和Slurm作业取消不等于这些能力。小图correctness不能补足该实现缺口。
4. **更广的联邦物理优化。** 当前自动搜索以已声明source的等价副本placement
   为主；一般性的单个Traverse内部跨分区拆分、join顺序/下推/fusion等自动搜索
   尚未实现为通用入口能力。已有显式split-data联邦执行仍是真实功能。

自动发现任意数据分区、通用流式执行和查询取消是系统能力边界，不是新增语言
算子的理由。窗口、任意UDF、无限递归、一般outer join等已经明确在第一版语言
范围之外，不应成为无限增长的当前开发清单。

成本模型校准、真实模型准确率、规模曲线和SOTA比较主要属于参数/评价证据，
不能仅因其尚未取得而说“没有planner”“没有LLM功能”。评价也可能暴露新缺陷，
因此代码存在并不能预先证明它适合真实负载。

## Catalog状态的纠正

新入口只读取显式固定的bundle，不在问题执行中构建目录。检查到的Freebase
问题入口注入catalog并调用retrieve/prompt_view；GrailQA有独立build脚本，论文
pipeline检查既有目录。当前没有依据宣称这些入口“每问一题都重新build”。
仍待完成的目录相关收口应具体记为旧数据格式/版本到新bundle的接线、真实样本
覆盖与读取验证，不能笼统退回大catalog重建。目录质量失败和构建失败分开记录。

## 今天能完成什么

以已冻结的有限语义、显式声明source、有限请求预算为范围，**今天收口一个可运行、
可复现的小数据研究原型是可行目标**；其确定性骨干现在已有真实双库验证。真模型
五题闭环取决于正在排队的3804011：最新预计北京时间18:28:27启动，但尚未获得GPU，
启动估计不保证实际开始时间或运行成功。

**今天完成原设计全部系统能力，不能诚实承诺。** 通用streaming/取消、广泛自动
拆分优化以及所有入口统一并非只差一轮full run。也不能把“今天可跑的有限原型”
标成完整Goal已完成，或为了声称完成而临时改变研究范围。

当天工程应优先复用既有能力、闭合必要接线、取得小图真模型结果并固定可评价
版本；不继续扩充无关框架或UI。首个真实数据接入使用小型集成样本，模块开发
继续使用toy。9月18日新增真实实验结果的硬截止和原有评价分母保持不变。

## 本次核对的代码入口

- `src/xgap/agent/question.py`、`agent/semantic_execution.py`：当前正常调用链。
- `src/xgap/runtime/semantic_planning.py`、`semantic_compiler.py`、`scheduler.py`：
  placement搜索、实际执行与中间结果边界。
- `src/xgap/agent/memory.py`、`runtime/adaptive.py`、
  `experiments/m15_method_policy.py`：已有memory/adaptive/消融模块。
- `src/xgap/llm/interpretation.py`、`experiments/toy_live_interpretation.py`：模型接口和五题联通。
- `src/xgap/catalog/build.py`、`catalog/bundle.py`、`experiments/freebase_question.py`：目录生命周期。
- `src/xgap/ui/local_app.py`、`ui/local_control.py`、`tools/remote.py`：现有UI与remote边界。

历史专用机制验证与现代骨干验收按版本分别引用，不互相替代；见
[当前T3-A报告](static_semantic_selection_20260911.md)、
[有限语义契约](../bounded_query_profile_v1.md)、
[M15历史机制记录](../m15_agentic_federated_core.md)。
