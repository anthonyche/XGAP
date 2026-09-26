# 48 题真实小批次交接

代码已提交为 `b86ada52433b2fd1f82dbf0b77d893d35be7b006`。
包：`/Users/anthonyche/Downloads/xgap-small48-b86ada5-v1.zip`，121,739 B。
SHA-256：`bd3b2c2a9002a4a0dbae1347802a20cd55931fb7bb6a87409cf38cb149dbc00f`。

该包从服务器现有 `XGAP-pilot-D1-auth-c402547` 增量部署，保留所有旧结果。
48 个已冻结问题、216 个适用方法请求，执行 D1→D3→D2，一轮；完整源快照不变。
先零调用重新发布和检查，再隐藏输入现有 API key，唯一提交 8 CPU / 24 GiB 作业。
无固定节点、无 GPU；study 六小时，Slurm 六小时十五分。具体上限和统计口径见
[执行合同](../decisions/ch6_small_real_execution_20260926.md)。

本地已完成：入口等价转换 35 项定向检查、live probe 31 项、会话复用及关联批次
37 项、48 题选择/发布 8 项、汇总器 5 项、规模/并行 2 项；这些检查范围有交集，
不将其相加宣传独立覆盖。真实 Neo4j/Fuseki 各一次 COUNT 通过；实际小批次镜像
696 个 pin、30 项发布检查通过。包的八项成员/哈希/源码/预算/CPU 配置检查通过。

归档中的具体 NL 错误已查明：主要为身份字段表示拒绝，不是所有模型响应都无法理解。
48/60 旧拒绝可通过修正后的编译，不等于新增 48 个正确答案。实际 probe 可用率、
选择率及 NP 差别由新运行决定；已有公共符号分支没有选择 probe 的证据保留。

上传此 ZIP 到 `/home/hxc859` 后执行一次：

```bash
python3 -c 'from pathlib import Path; import hashlib,zipfile; p=Path("/home/hxc859/xgap-small48-b86ada5-v1.zip"); assert hashlib.sha256(p.read_bytes()).hexdigest()=="bd3b2c2a9002a4a0dbae1347802a20cd55931fb7bb6a87409cf38cb149dbc00f"; exec(compile(zipfile.ZipFile(str(p)).read("stage.py"),"stage.py","exec"))'
```

出现隐藏输入提示时填写现有有效密钥；命令行、归档、Git 均不包含密钥。
已有相同 stage/结果目录会阻止重复提交，不删除防重复记录。

新作业日志位置为
`/home/hxc859/xgap-ch6-artifacts/small48-b86ada5-v1/small48-<jobid>.out`。
结果位置为 `/home/hxc859/xgap-ch6-artifacts/small48-results-b86ada5-v1`。
正常或可捕获的失败结束后生成 `~/xgap-small48-<jobid>.tar.gz`，自动带回实际
逐请求/分组 CSV、完整成本与覆盖、编译诊断和预算截断状态。外部硬终止仍需回收
已有记录，不能假设一定成功生成归档。

此包不启动每域 800 题或全套因子扫描。规模与并行代码/配方在同一提交中，实际
D4 服务物化和后续扫描另行执行。本机没有提交新服务器作业，整体 Goal 未完成。
