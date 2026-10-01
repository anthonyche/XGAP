# 外部方法已运行；保持原生结果，不修 baseline

FedX和固定版本FedUP已经在9条事实、两个真实Fuseki源上运行，能够保存答案、失败、
源端请求和费用。按用户最新原则，baseline只需能运行并如实记录，不要求全部答对。
FedUP的排序错误与聚合失败保持原样，不再阻塞XGAP工程。

这是tiny接入证据，不是论文准确率、速度对比或完整FinBench成绩。用户批准的
FinBench原生/同事实RDF优先级、随后有界FedShop和保留GrailQA/R1均不变。

## 实际结果

| 检查 | FedX 5.1.2 原生库 | FedUP 固定commit、原生FedX执行路径 |
|---|---|---|
| 两源join，要求账户降序 | 两行且顺序exact | 两行内容正确，但返回升序，ordered exact=false、bag F1=1 |
| 两行相同投影值的bag | 保留两行，exact | 保留两行，exact |
| 没有匹配值 | 成功返回空答案，exact | 成功返回空答案，exact |
| COUNT/SUM + GROUP BY + ORDER/LIMIT | 一行，count=2、weight=3，exact | HTTP500，零源请求；原始代数错误保留 |
| 无效语法 | HTTP错误，零源请求 | HTTP400，零源请求 |
| 明确注入单个源503 | 返回错误；所有源尝试记录 | 原生可能返回HTTP200；有6次源失败，评价记录明确失败，不当成功空答案 |

这些案例混合了答案检查和故障注入，不能把“通过几项”写成数据集准确率。
没有重排FedUP的答案让它通过，也没有删除其聚合题或改用另一个引擎挑最好结果。
上游 `FedQPL2FedX.visit(OpOrder)` 未传递降序方向，聚合相关访客也未完整实现；
这是固定版本的局部诊断，不泛化成所有FedUP配置或论文的能力结论。

主要原生证据：

- 首轮：[原始收据](/Users/anthonyche/xgap-data/external-federation-tiny-20260912-v1/receipt.json)，FedX五项接入行为成立；FedUP正常请求受观测器HTTP兼容错误影响。
- HTTP修正：[FedUP收据](/Users/anthonyche/xgap-data/external-federation-tiny-20260912-hop-headers/receipt.json)，只补验四项受影响请求，复用冻结summary，零重建。
- 新聚合边界：[原生聚合收据](/Users/anthonyche/xgap-data/external-federation-tiny-20260912-native-aggregate/receipt.json)，两种方法各一次。
- [统一证据索引](/Users/anthonyche/xgap-data/external-federation-gate-seal-20260912/receipt.json)绑定每一项原始artifact；错误状态的旧收据不被覆盖成成功。

## 环境、计量与失败归属

FedUP源码commit仍为`4c1a3aa8137a3940f7f8255397cb8fec717c8afa`，Java21构建
69.746秒成功；[构建收据](/Users/anthonyche/xgap-data/fedup-build-20260912-v1/receipt.json)
固定3个不可变jar。上游源码干净，FedX库未修改。依赖准备属于离线成本。
只执行一次9事实TDB装载537.859ms和summary构建1344.762ms；后续复制冻结summary、
显式更新endpoint映射，未再构建。summary hash模数1与原生server一致。

共同观测器记录每次源请求、ASK、请求target/body与响应body字节、错误、原始响应
及hash；这些是HTTP应用载荷，排除headers/TCP/TLS，不能标成总网络字节。初始化
独立标记，方法进程在其检查块内持续运行。每条顶层查询8秒wall deadline，源端
3秒，整个tiny环境240秒，响应上限16MiB；超限/错误不转成功截断结果。

首次观测器错误是将HTTP2-Settings/Upgrade跨hop转发给HTTP1源，导致ASK HTTP400。
修正只剥离连接级header，不改SPARQL、不改FedUP。四项新的局部检查分别覆盖bag/
顺序、RDF term身份、嵌套wall deadline和HTTP升级头隔离；均通过，未重跑旧核心。

上游ASK内部失败最多尝试5次，最后可按false处理；原生SERVICE也可吞源错误。所有
实际尝试照计，不能称整个baseline“零重试”。外层提交每个声明请求一次，保留
native HTTP状态/原始答案，并用源错误记录区分“引擎返回”与“可信执行成功”。
我们的环境故障不进入正式方法准确率；原生方法的错误/不支持则留在冻结评价分母。

## 已撤回的能力扩展

在用户明确补充原则前，尝试过由Jena补FedUP外层聚合/排序的组合封装。它会扩展
baseline能力，现已从仓库执行入口撤出，不纳入正式方法。六次development请求中，
四个正常答案请求受standalone结果reader/writer注册问题影响；另两项为语法/源故障
注入。后续注册修正build未执行。原日志和两次
build保留在仓库外，[隔离收据](/Users/anthonyche/xgap-data/fedup-composition-quarantine-20260912/receipt.json)
明确不可进入论文结果。不会继续修它。

本轮共22次tiny顶层尝试、131次源HTTP请求，其中被隔离组合封装6次/50次；正式
实验调用为0，LLM/训练/大数据调用为0。这些失败和花费均保留，不省略成“首次即通”。
所有拥有的服务与观测线程已终止，输入指纹未变。

下一步是FinBench同事实RDF与XGAP普通入口的参数/NL/reference接入、独立样本及预算
冻结。baseline保持原实现能运行即可；不为其错误做额外算法修复/语义补全/调参。
