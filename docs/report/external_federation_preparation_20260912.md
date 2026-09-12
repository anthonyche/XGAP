# 外部联邦对照：已批准优先级后的首个接入检查点

用户已回复“按建议优先级推进（推荐）”：先FinBench原生与同事实RDF的FedUP/FedX，
再做有界FedShop；GrailQA/KBQA-R1保留，不作为前两轨启动前提。具体数据、独立答案、
运行预算和薄适配门槛还需完成，当前尚无新外部对比成绩。

## 可复核的外部版本与配置

FedUP HEAD通过公开Git读取确认并固定为
`4c1a3aa8137a3940f7f8255397cb8fec717c8afa`。对应源码已完整获取，detached checkout
与该SHA一致且干净。源码保存在
`/Users/anthonyche/xgap-data/external-sources/fedup-4c1a3aa-system-proxy`，未修改其算法。
获取收据在 `/Users/anthonyche/xgap-data/fedup-source-intake-20260912/receipt.json`。

该提交的pom声明FedUP0.1.2、Java21、RDF4J/FedX5.1.2、Jena5.5.0。CLI注解仍显示
0.1.0，因此以commit和pom身份为准，不能只依赖帮助文字。实际源码`FedUP.getFedX()`
固定bound join block10、join workers10、union workers10，内部query最大时间是
Integer.MAX_VALUE。对照要明确匹配线程/批量配置，并由共同外层watchdog限制运行。
[固定版本的pom](https://raw.githubusercontent.com/GDD-Nantes/fedup/4c1a3aa8137a3940f7f8255397cb8fec717c8afa/pom.xml)。

FedUP提供自己的server CLI、summarizer和计划输出；可以复用它们，避免改造外部
算法。summary必须离线冻结，默认endpoint映射针对其示例部署，不能原样套到本地
实验。初始化、source-selection ASK和实际fragment均需在共同调用观测边界内记录。
不为XGAP预先提供FedShop的gold source assignment。

## 下载失败与有依据的配置修正

四个仓库的原公开commit API请求均URLError。随后Git只读ref成功，首次直接fetch
45s超时；首次FedX Maven构建11.230s失败于编译插件下载，未进入Java编译。Maven
报告repo.maven.apache.org解析为198.18.0.75并连接超时。这些失败保留，不计为模型或
数据库查询失败，也不删除后重新报告“第一次就成功”。

只读检查发现系统已经启用HTTP/HTTPS代理127.0.0.1:1082，当前进程没有proxy环境
变量。新建的显式构建/获取配置使用该已有通道，未更改VPN、系统代理、用户凭据或
全局Git/Maven配置。新配置的FedUP获取2.075s成功；Maven下载恢复。每个配置只执行
一次，依赖准备/网络费用属于离线artifact成本，不伪称免费。

FedX原失败收据：`/Users/anthonyche/xgap-data/fedx-adapter-build-20260912-v1/receipt.json`。
新构建的独立日志/收据：`/Users/anthonyche/xgap-data/fedx-adapter-build-20260912-system-proxy/`。
本机已存在Maven3.9.12和Java21；构建显式使用Java21。默认Maven环境是Java25，
没有将该默认环境误报为Java21。

## 薄适配范围与接下来的门槛

`experiments/external/fedx`仅将官方FedX库包装为持续运行的本地SPARQL SELECT服务，
不经过XGAP的编译器、估计器或planner，不手写替代FedX策略。它保留原生source
selection/cache，拒绝UPDATE，输出标准SPARQL JSON；失败不转换为空答案，超出
结果预算不返回成功截断结果。一次只接受一个顶层查询，不能据此宣称吞吐并发能力。

构建与帮助命令只是适配准备检查；actual tiny query、结果bag/order规范化、共同
backend请求/bytes观测、全局watchdog以及同事实金融RDF映射尚未完成。不用源码
下载成功或编译通过冒充外部方法已复现。下一步按这些具体门槛推进，每个新边界仅
运行必要tiny检查；不重跑旧XGAP核心、训练、NL成功请求或旧48题比较。

## 当前构建结果

新代理配置构建238.117s成功，Java21编译通过，帮助入口exit0，源码指纹不变，模型/
backend调用均0。冻结jar大小30,724,855bytes，SHA
`c1efab4fd7d5f2d6876b22f8a09fc8f11a902d88c5b077314d183cdb9cc4f0b2`。
不可变副本在新构建目录的`fedx-endpoint-adapter-v1.jar`；之后复用scratch target目录
不会销毁这份已验收构建。对应[外部artifact锁](../../experiments/environments/federation_external_artifacts_v1.json)
保存版本、源码/产物hash与失败收据。

随后依据已取得的FedUP源码，把FedX批量/线程显式设为10/10/10，并按原实现注册
standalone JSON/XML结果reader。仅针对这个新配置，用已下载依赖离线重建5.067s
成功，帮助入口exit0，零网络/模型/backend调用。当前jar为30,725,161bytes，SHA
`2e12c2630a94e017401ca8287b20ab90c0550a6607d19030a843a7d42d5f1290`，
位于`/Users/anthonyche/xgap-data/fedx-adapter-build-20260912-matched/fedx-endpoint-adapter-matched.jar`。
原构建及不可变jar保留；没有因该修正重跑旧软件测试。共同外层时限/计量、FedUP
构建和native query gate仍待完成。没有外部库或
本地服务进程留在运行状态；两次构建和两次不同获取配置的结果分别保留。
