# 外部方法环境接入：原接口已可用，端到端仍待验收

2026-09-21。ARUQULA 作者代码固定
`9a3982baca03d62f7250572e300b1e4ba47727cc`，未修改算法、提示、搜索、修复或模型解码。
全部步骤为离线环境/接口准备，模型调用0，不是外部方法实验成绩。

|边界|本次结果|证据|
|---|---|---|
|原依赖|安装成功；保留首个300s安装截止记录|`aruqula-runtime-20260921-v1/install-2-receipt.json`|
|核心导入|成功，作者 tracked source 未变|同目录 `import-2-receipt.json`|
|Redis|官方8.10.2源码 `498ecd0d6d007db11ddb3aea9428552598a78622` 编译；原 `kg_utils.client` ping/set/get/delete通过；服务关闭|`ch7-redis-admission-20260921-v1/receipt.json`|
|Lookup|DBpedia官方源码 `939b3f36fefafca444cc6dff6c568c5b559f58e0` 编译；官方示例ontology索引、HTTP查询和原 `search_span` 均返回预期示例URI；服务关闭|`ch7-lookup-admission-20260921-v3/receipt.json`|

路径均在 `/Users/anthonyche/xgap-data/`。两个实际接口门的 SHA-256：

- Redis：`78673c4925b97eb8d0c712e2294acd500294b4b805bf21bca5d4459af7523b0c`。
- Lookup：`3dd3e58924e52ef3ab4ebc709c1a6bf531b4c1b8bc693f5aeeb62fc66c8d5815`。

## 保留的失败和环境处理

Homebrew 安装 Redis 在 ca-certificates bottle 的安装元数据处失败；官方下载站返回403。
随后从官方 GitHub 8.10.2 tag 取得同版本源码，按官方 Makefile 构建，版本号与commit核对。
仅启动专属临时服务于127.0.0.1；不清空已有缓存，不操作共享服务。

Lookup 原 `jar-with-dependencies` 在启动时缺 Lucene99 SPI；其打包覆盖了重复服务注册文件。
通过官方 POM 的 `dependency:build-classpath` 获取原版本依赖，采用 thin jar + 独立依赖 JAR
启动，保留 Java 正常的服务发现。这是 classpath 配置处理，未改 POM、依赖版本或搜索算法。
v2 启动失败回执保留；v3 接口门单独封存。第一条命令在导入 requests 前失败、未启动服务；
接入脚本随后使用标准库，保持 XGAP 的测量环境依赖不变。

## 尚缺什么

还需要为真实冻结图提供所有方法均可访问的公开 metadata/lookup 索引，配置现有 Qwen
模型接口，接通 ARUQULA 原生流程和实际 FedUP 执行，并统一记录模型/探索/最终执行成本。
这些完成前，RDF 能力表仍为 SETUP_ERROR；不把依赖安装成功当作方法已复现。
原方法只提供 SPARQL 接口，Neo4j+Fuseki 混合部署记 UNSUPPORTED，不给它发明新适配算法。
