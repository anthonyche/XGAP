# 五方法批处理与远程准备进展

同一已暴露 tiny 问题、8 实体/16 关系、同一公共问题和 RDF 快照。不是 held-out，
每方法只一次，不据此声明性能优势。源码 `470aa57`。

|方法|结果|请求耗时 s|模型调用|源请求 attempts|
|---|---|---:|---:|---:|
|XGAP|完成，EM=1|9.620|1|9|
|NP|完成，EM=1|8.876|1|9|
|SH|完成，EM=1|6.064|1|9|
|GR|完成，EM=1|7.019|1|14|
|TS|观测额度截断，质量不可评分|80.615 至截断|37|261|

TS 实际转发 256 次源请求，额外 5 次被预定观测额度拒绝；模型输入/输出 tokens
63,761 / 3,908，无最终计划提交。不可将截断耗时画成完整答案耗时，也不计作错误答案。
原始通用评分器给出的 0 不修改；后处理按 `harness_call_budget` 标为 study-censored，EM/F1=null。
支持范围仍是 supported，不能用失败倒推出“不支持跨源”。没有为质量调参或重跑 TS。

首个 invocation 遇到观测额度后停止；确认全部资源关闭后，仅继续从未运行的 GR/NP/SH。
两次 invocation 均关闭全部 owned 进程，五 cell 全部封存，没有重复执行已尝试 cell。

证据根目录：`/Users/anthonyche/xgap-data/ch6-five-method-gate-20260923-v2`。
manifest SHA-256 `8e35ebf502c4d984f1bf8379b74a4086308b1a4c8d48988e9dcec965c8c49311`。
第一次 receipt `3d5cb3adb947ede5cd0e33a7e05b8a0ff909dcba9dee3681aa86ac4d21971948`。
第二次 receipt `347d194b78ec5360a40b371b87f988731c34c98ef0a7926c390805142bbec079`。

此前 v1 的 Python 虚拟环境路径与旧 frontend 引用失败保留。修复仅恢复已准入运行配置。
新的混合 workload 支持集合/配对规则有 9 个定向测试通过。此前模块定向验证 41 passed；
不将重叠测试累计成独立测试数，不宣称所有历史回归通过。

仍不能称全量 ready：三域 held-out/因子输入、F6 等价成本池、正式样本/资源预算和
Linux 五方法运行环境尚未全部冻结。远程 CPU 授权和已验证事实见
[CWRU 决定](../decisions/ch6_cwru_cpu_20260923.md)。
