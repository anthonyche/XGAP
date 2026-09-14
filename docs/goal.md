# XGAP Active Goal — Research-directed, Toy-first Development

## 当前工程：performance 关系读取预算已实现，真实 tiny 验收待运行

原group9–10已全部封存；目前不重跑评价题。按用户观察实现可选
`retrieval_rows_per_relation`：原生关系查询LIMIT B+1，保留B行并记录漏行；
节点身份/属性完整读取，估计器只缩减返回/后续输入工作，原权重和扫描工作代理不变。
聚合/排名在观测子关系上执行；full-source exact标志、最终answer和紧凑handoff明确
保留近似范围。显式完整结果要求在模型/数据库调用前拒绝预算冲突。旧默认不变。

[设计、Ptime与准确性边界](decisions/budgeted_relations_v1.md)。9个独立新风险案例已通过；
后续定向重跑只覆盖改动的fixture/handoff/超额返回成本记录。实际SPARQL小图8关系→
返回3/保留2，COUNT8→2且full-source EM必须仍为0；该门不是论文提速结果。
真实Neo4j/Fuseki新tiny脚本已离线确认普通估计可用；下一步只运行一次该外部边界，
复用冻结8节点16边及统计，不load/fit/model/baseline，不重跑旧问题。

precision完整执行保持；其解释/grounding一致性增强仍待实现，两模式新profile尚未
发布到正式campaign。其后再冻结模式预算并讨论/执行真正的速度—质量评估。
NL唯一journal下一group11、所有44结果保留；Native fixed20/RDF fixed5不变。
9月14日10点已恢复，整体Goal active，无未来暂停。以下旧“当前”段为历史。

## 2026-09-14 10:00 北京时间已恢复执行

用户已明确恢复时间为9月14日上午10点，现在继续工程。旧暂停到期；9月15日恢复
是助手对同一指令的误解，已撤销。先完成当前one-shot中间数据生命周期/紧凑trace
里程碑：保留完整最终答案、节点计数与源响应回放，验证共享/并行消费和失败；仅运行
新风险小图与必要真实tiny边界。验收后继续未运行NL group8，新实现epoch记录。
整体Goal保持active，未完成系统/论文评价；不重复旧大题，不优化baseline结果。

以下旧状态为历史；以本节及随后当前里程碑报告为准。

## 当前优先级：当前实验已结束，按用户观察强化两模式的实际差异

用户要求先跑完当前实验，再分析更激进的performance和更精确的exact/precision。
新group9–10八方法已封存，所有服务/控制器96519终态。两XGAP模式都正确：group9
空答案（精度37.903s/性能36.715s），group10为10行非空exact（36.028s/38.902s）。
两模式每题6源请求76995602B、相同实际执行nodes，各仅1解释、0grounding lookup。
FedUP两次原生失败；FedX两次共同响应预算censor；8模型调用24328输入3929输出token。
[逐题结果、实现审计和下一小图里程碑](report/mode_differentiation_20260914.md)。

当前performance仅减少解释/grounding候选和关闭ontology，执行层近似检索尚未实现；
precision的软质量权重/按artifact顺序grounding也不保证更高精度。先转回tiny实现真实
预算化检索/扩展、明确聚合与排名近似边界，并加强精度模式解释/grounding一致性验证。
预算必须在昂贵操作前生效，Ptime/冻结估计/单最终计划不变；不能人为拖慢precision、
把快速失败当收益、调旧评价题、改baseline或无限加回归。新mode门通过再继续评价。
唯一NL equality-v1 journal下一group11（全部44结果保留）；Native fixed20、RDF fixed5。
已验收保留工程246f3f0/a23a1fa及group8证据保留。整体Goal active，9月14日10点已恢复；
没有未来暂停。Sep14 17:00/ Sep18目标保持；两模式新差异尚未实现，不冒称系统已全部完成。

以下为历史记录；旧暂停/待运行group及旧next方向以上方为准。

## 当前执行：冻结键上界与真实NL两模式已接通；下一门为中间数据保留

630d802/e9acb6b完成可选离线等值字符串键上界，按source/snapshot/namespace/label/property
冻结，接入原估计器和实际绑定限额。16个新风险案例通过；tiny普通入口4行非空exact，
模型自己选一个计划，14源调用，1.412s在线，零LLM/fit。[当前完整报告](report/equality_key_bounds_20260913.md)。

完整RDF源各55604实体的业务id统计9.206s离线冻结，原事实/权重/baseline/prompt不改。
保存原路由诊断：coordinator834.612ms不变，fanout12842.692→777.969ms，上界10000→2，
模型自行选择fanout；不是重试旧问题或实测提速。source-only统计，无答案或当前查询采集。

新journal finbench-rdf-nl-campaign-20260913-equality-v1继承全部旧28结果后首次运行group7。
两XGAP模式均1次模型、1个估计选中的fanout计划、14源请求/182844047B，正确空答案EM1；
完整80.876/84.423s。FedUP原生失败EM0；FedX共同响应预算中断EM0；四方法合计4模型调用、
12296输入/2015输出token。不是总体/非空NL准确率或模式Pareto/提速结论，旧分母/失败不改。

下一tiny门：scheduler保留所有中间rows，trace再物化它们，两个成功完整trace各604MB；
精度RSS2.111GB接近原2GiB限额。先验证仅one-shot的中间数据生命周期与紧凑trace，
保留最终答案/节点计数/实际源请求与failure replay，再进入未运行group8。不要重跑旧大题。
该门设计尚未实现；不扩大为通用产品、不修改baseline优化结果、不重新训练毫秒回归。

当前NL下一8（新equality journal；旧journals仅证据）；Native fixed下一20、RDF fixed下一5，
native NL未启动。120=24/48/48，评价33空15非空保持；FedShop旧下载失败不重复，3804210
由用户更新。所有新句柄终态，包括35646/36948/47645/61840/43591/19763/61916/71240；
新campaign三次session关闭均drained/terminal/observer stopped，空闲11.264GB，6GiB reserve。
Sep14 17:00核心/接口、Sep18论文结果不变；Goal active，用户已继续，旧暂停无效。

以下为前序记录，执行状态以上方为准。

## 当前执行：名称/ID/变量入口3题通过；真实NL下一缺口为去重与聚合约定

4509c15发布独立prompt-v2和只派生prompt的冻结配置，原v1、wire/compiler/grounding/
planner/估计器/预算/数据不变。3项新检查首次通过0.35秒；真实冻结8节点16边小图上
名称、业务ID、普通变量三个新NL请求各1次模型、1个估计选中的最终计划，答案全exact。
名称Alice查catalog1次，其他0次；源调用3/10/3，完整2.341/3.524/1.451秒，合计
6404输入/895输出token。无重装/fit/baseline/probe/retry，控制器和服务终态。
[小图证据与准确范围](report/compact_roles_20260913.md)。

新native/RDF全量profile及原冻结stores/FedUP summary的关联已离线封存，零新load/
catalog/训练/summary工作。RDF NL新journal引用原8个失败结果，保留全48题、方法顺序、
版本及曝光，从未运行group2继续；旧题没有重提。该组四方法各1次模型后均在compact
lowering拒绝：company/account去重键没有保留SUM所需transfer身份。普通变量都已正确
填entity:null，名称问题这次未出现。最终计划0、源0、分数0、约8.24–8.82秒/方法。
不是baseline原生失败或catalog问题，未修模型回答。[真实新失败及含义](report/finbench_nl_third_group_20260913.md)。

另完成native fixed未运行groups12–15，时间v2语义下4个正确空答案，零模型，单计划，
16.713–29.916秒，方法峰值0.921–1.789GB低于原2GiB。原wrong/censored结果保留；
这批全空，仍不证明时间修复后的真实非空效果或提速。所有句柄49874/52689/86785/5140
已确认exit0，全部服务终态。Native fixed下一group16；RDF fixed下一group5；RDF NL
prompt-v2新root下一group3，已含旧8次失败引用；native NL仍未启动。

下一门：先在独立tiny parallel-transfer/multiple-witness例子上澄清有界逻辑语言的
去重/聚合约定，再实现必要版本化lowering。不要继续盲目加prompt或大数据模型重跑；
不能将v1无效回答静默补键/丢约束。真实策略估计排序、完整NL、FedShop/scale及最终
批准图表仍未完成。保留120=24/48/48、评价33空15非空、所有首次失败与版本边界；
baseline只忠实运行原作者方法，不帮它优化。Sep14 17:00核心/接口、Sep18真实论文
结果目标不变，Goal active；旧暂停解除，不轮询3804210。

## 以下为前序记录；执行状态以上方为准

## 当前执行：真实非空答案已取得，时间格式缺陷修复，NL 实体角色是下一瓶颈

626bb84精简native身份投影；同一tiny答案/5次调用的源传输13,800→4,907字节
（减少64.44%，不宣称时延提速）。按原顺序新运行native fixed groups8–11：两题
正确空、一题正确非空（1行）、一题错误非空（10行，EM0/F1.8）；15.4–28.0秒，
方法峰值0.943–1.362GB，均未超过原2GiB预算。旧8题/3次内存中断不重跑、不合并
版本计时。[逐题证据与修复](report/native_projection_timestamp_20260913.md)。

错误非空题的保存记录定位到时间词法：79,909条转账中8,017条省略小数末尾零，
旧过滤器只认3位；该题漏掉10笔合格转账。独立保存输入诊断解释完整top10差异；
原评分不改。08eb4f0使timestamp_ms支持有效本地日历时间的0–3位小数，共同NL
SPARQL与coordinator一致。4项新检查首次通过1.32秒，含tiny估计选一计划完整链；
一次真实Fuseki VALUES核对23边界全过，服务终态，零模型/重装/fit/baseline。

随后按顺序完成RDF NL group1四方法各1次模型调用：全在grounding停止，源查询0，
答案分数0。模型把person等普通角色误填成待识别实体；冻结catalog正常加载并返回
零匹配。这不是catalog build failure或FedUP/FedX原生执行失败。不改prompt/catalog、
不修该题、不重试。约8.66–9.23秒/方法；原group0四次解释失败继续保留。
[NL逐题结果与含义](report/finbench_nl_second_group_20260913.md)。控制器全部exit0，
所有服务终态。最后一次编译修复08eb4f0；本轮不是系统/论文评价全部完成。

下一步用小图和failure replay明确实体名称/业务ID/普通变量的Interpretation约定，
之后版本化继续未运行评价；不要继续无差别模型调用、不把未解实体直接丢弃。
Native fixed下一项group12、native NL未启动；RDF fixed下一项group5、NL下一项group2。
保持120组24/48/48、评价33空15非空、原baseline算法/配置/所有失败。核心Ptime与
估计选一计划不变；不重建catalog/重训毫秒回归。剩余普通NL可靠性、实际策略排序
效果、FedShop/scale及批准图表仍需完成。Sep14 17:00核心/接口、Sep18真实实验目标
不变，Goal active，用户已恢复工作；不轮询3804210，不恢复旧暂停。

## 以下为前序记录；执行状态以上方为准

## 当前执行：native 共同评价已接通，8组真实结果与内存中断保留

f0ce1df接通冻结Neo4j/control-Fuseki副本、共同observer/worker/评分/调度，新增明确
xgap-native标签，普通NL两模式沿用原入口。首个tiny准备因相对prompt路径失败，
2965d5b只修路径不改prompt；失败留存。5项新风险检查0.53秒及1项失败回放0.30秒
通过，不重复旧门禁。新tiny副本链1个计划/5次源调用，独立非空答案company1=56
exact、在线1164.191ms、零重装/模型/fit，全部组终态，原冻结输入不变。

按事先顺序两批运行native固定语义前8组：5个正确空答案、3次2GiB方法RSS超限中断。
8题gold全部空；尚不证明真实非空/NL效果。完整在线约22–43秒，源117–243MB/题。
一类路径的两次全量转账边读取各106.716MB；保存的Cypher返回完整实体对象，再在
绑定归一化提取身份，已定位为待验证的传输低效。尚未证明这是唯一瓶颈或估计器
排序错误，不提高预算、不重试失败大题。两批控制器exit0，全部服务退出，130个
冻结store文件再次核验不变。[工程、逐题结果及边界](report/native_campaign_first_eight_20260913.md)。

下一步优先tiny验证精简身份投影，保留节点/平行边身份、属性与跨源连接语义；
不先重训估计器、不优化baseline。保存本次实现与曝光边界，未来版本时延不得静默
混算。Native fixed下一项group8；native NL清单96单元尚未运行。RDF fixed下一项
仍group5、RDF NL group1。总120组24/48/48、评价33空15非空不变；剩余真实非空、
整体NL、FedShop与批准图表/消融仍须完成。Sep14 17:00核心/接口、Sep18论文实验
目标不变，Goal active；用户13:32已恢复，旧暂停无效，不轮询3804210。

## 以下为前序记录；执行状态以上方为准

## 当前执行：首个 NL 评价失败已封存，完整 native 数据库已冻结

首个冻结普通NL问题已由四个方法各调用模型一次：四份紧凑响应相同，均将路径变量
用于只允许节点/边变量的去重键，因此被拒绝。模型4次、最终查询0次、源调用0次，
每方法该题答案分数0；失败不等于正确空结果。这是共享解释前端失败，不能记为
FedUP/FedX原生执行失败。没有重试、修答案或改prompt；全部进程终态。
[NL结果与解释](report/finbench_nl_first_group_20260913.md)。

新native离线装载器在小图和完整SF0.1首次均成功。完整194批次、55,604节点/
309,577关系计数一致，33.805秒完成装载、两次完整性计数、正常关闭和冻结；原输入、
catalog及32条观测模型不变。3项新风险检查0.28秒通过，未重复成功门禁。
[装载证据和准确边界](report/native_store_preparation_20260913.md)。实现7a99c56；
CSV格式修正cdb6ce6不改方法逻辑。prep原件不可在runtime重载/修改，后续服务复制使用。

下一步接通native冻结副本的服务/共同observer/runner，再执行批准native评价；
RDF固定语义从group_index5、NL从group_index1续跑未执行单元。新增离线脚本改变
实现tree pin，继续旧campaign需显式追加harness epoch并说明方法逻辑未改变，不能重跑
旧intent。完整系统/全部评价尚未完成，仍需native实际评价、有界FedShop和后续图表。
既有固定轨四题XGAP30–33秒/FedX1.08–3.25秒的负结果保留，未证明提速；只在开发/
训练集诊断数据搬运与排序。120组及24/48/48、33空15非空分母冻结。Sep14 17:00/
Sep18目标和用户13:32恢复指令不变，Goal active，不恢复旧暂停，不轮询3804210。

## 以下为前序记录；执行状态以上方为准

## 当前执行：真实 RDF 评价已发车，首批负结果与设施修复保留

首个固定语义block已处理冻结顺序5组/15单元，实际方法查询14次、模型0次。
XGAP5题均返回正确空结果；FedX4题正确空结果，首题因本机端口耗尽未取得答案；
FedUP4次原生聚合HTTP500、首题设施故障未执行。所有5题gold均空，不能据此声称
非空/NL质量。四个可比问题XGAP约30–33秒、FedX1.08–3.25秒，当前没有提速证据。
[真实逐题结果、成本和限制](report/finbench_rdf_first_five_20260913.md)。

44.885秒一次性作者summary、方法host、总预算、分批调度/评分已接通。观测器改为
HTTP/1.1有界空闲连接复用，不缓存/重试；会话先脱离再回收，修正legacy killpg退出
竞态（1a122d1）。修正使用小故障回放，历史输出、15个intent、源/summary/题目冻结
不变；只续跑了此前未执行单元。三段harness版本明确记录，不悄悄混合时间。
全部查询及本轮控制进程已终态；曾等待observer的控制进程经身份核验后退出143，
随后正常续跑退出0。10项不同新检查通过，不重复旧门禁。[原生准备报告](report/fedup_campaign_preparation_20260913.md)。

下一步从group_index5的未运行单元继续，并启动普通NL轨；需要非空答案证据。
固定RDF轨已实际可执行，整体研究原型/全部评价仍未完成：还包括native双库轨、
有界FedShop及其余批准实验。保持原120组24/48/48及评价33空15非空；不因负结果
调整baseline或重采样。XGAP中间数据搬运已显示高成本，后续只用开发/训练数据区分
策略空间与排序估计问题，保留首次评价和曝光边界。Sep14 17:00/Sep18目标不变。
用户9月13日13:32已恢复，旧暂停解除，Goal active。


## 当前执行：普通 NL 双 RDF 成功，共享外部 NL 接通并保留预算截断

a0d5ebf接通bounded global SPARQL、共享K3质量优先前端、共同NL worker/费用监督，
并修复普通one-shot对RDF实例估计器的类型准入。11项不同新风险检查通过，失败及
最小回放保留，不重复旧门禁。fd47ea3修正调用方不合法FedX启动超时，未改作者代码。
[真实结果与边界](report/shared_nl_native_20260913.md)。

一次真实XGAP performance NL→双RDF：模型1次、最终计划1个、源9次、金额66/9 exact，
完整3638.164ms。共享NL→FedX另有模型1次、编译1次、顶层查询1次；261个到达请求中
256转发成功、5被tiny代理上限拒绝。该次被验证预算截断，不是FedX答案错误或原生
语义失败，不用于优势比较。已保存查询的一次离线并集诊断exact，不冒充FedX答案。
没有重跑该query、优化baseline或重建catalog/model；全部8个服务进程退出。

完整SF0.1的新RDF离线版本已发布：55,604实体/309,577关系；复用原618MB graph，
生成50.107MB control元数据衍生文件，原59,587项catalog/32观测模型不变，零大数据查询。
[完整输入发布](report/full_rdf_profile_20260913.md)。配置SHA723e2517…，实际文件在offline.rdf_loads。
接下来正式每题预算/observer重置、服务装载与平衡campaign。正式预算不能照搬tiny
临时256次或跨题累计计数。完整服务未装载，formal_campaign_ready=false；外部NL已
触达真实源，但被截断那条的FedX完成答案仍未观察到，不重跑该题改善结果。

用户9月13日13:32已恢复工作，旧暂停解除；保持tiny开发/failure replay。120组与
24/48/48划分、评价33空15非空冻结。Sep14 17:00核心/接口、Sep18真实结果目标不变。

## 以下为历史交接，以当前执行为准

## 历史暂停交接：9月13日13:32已由用户提前恢复

用户最新指令：本轮完成并汇报后暂停，**2026-09-14 12:00 Asia/Shanghai
（04:00 UTC）恢复**。本节覆盖全部旧继续、小时推进或暂停指令；到时之前不启动开发、
测试、模型/数据库/训练、baseline或远程轮询。整体Goal仍active且未完成，不误记为
complete/blocked。原heartbeat已改为中午恢复，到时才接续并恢复小时推进。

f385709已接通独立RDF端点配置和冻结估计器投影。5项新风险检查首次全过0.47秒；
一次8实体/16关系真实双Fuseki gate，三类查询各只执行一个预选计划，全部独立答案
exact，graph/control共16次必要调用。零模型/baseline/fit/probe/retry；复用原数据和
原32条训练权重，输入封存不变，两个服务和进程组均已退出。
[完整进展、结果与限制](report/rdf_instances_native_20260913.md)。

本轮证明同事实RDF确定性链已实际接通，不证明总体NL准确率、排序最优、提速或scale。
新实例迁移未校准；完整SF0.1 RDF profile尚未发布，完整服务尚未装载，campaign_ready=false。
先前普通NL+真实双库成功、完整serving输入/catalog、120组population和worker守护继续
接受，不重跑成功门禁，不重建catalog，不为毫秒误差重训。评价33空/15非空保留。

明日恢复后先补共同外部输入/规范化评分、完整外层计时、托管服务资源和异常后静止
屏障，再发布完整RDF配置并按已批准协议运行FinBench native/RDF/FedUP/FedX，之后
有界FedShop，消融最后。baseline只需忠实可运行、如实反映结果，不替它优化。
Sep14 17:00核心/接口和Sep18真实实验目标保持；恢复后距前者仅5小时，优先必要接线。

## 以下均为历史进展；执行时间与下一步以上方最新门限为准

## 前序：请求守护与失败计分已接通

017a0d2新增180秒独立worker守护、采样RSS/日志/进程预算、进程组清理与失败终态。
5项新风险检查一次通过0.82秒；一次完整FinBench profile零调用预检通过，worker
2.872秒、采样RSS238.922MiB。中断题保留身份和分母，失败对空gold计0；部分用量
未知即保留unknown。没有模型/数据库/训练/方法运行或旧成功门禁重跑。
[本轮证据与准确边界](report/one_shot_process_guard_20260913.md)。

此前真实serving输入已冻结（161ef2e）：18表55,604实体309,577关系，59,587条catalog，
原model未fit，新source统计与两模式可加载；[输入证据](report/finbench_serving_profile_20260913.md)。
服务尚未装载执行，120题及33空/15非空评价分母不变。当前守护只覆盖方法worker，
父adapter完整成本、常驻server/数据库资源和异常后的静止屏障仍需共同runner接线。
下一步真正连接XGAP-RDF多endpoint的compiler/estimator身份、共同外部输入/评分，
再真实主评价/scale，最后消融；不替baseline优化结果，不继续反复做catalog。
当时暂停已到期并恢复推进；现受本文开头9月14日12:00恢复门限约束。

## 历史暂停记录：截至9月13日12:00（已到期）

用户最新要求：完成本轮milestone、汇报后暂停，**2026-09-13 12:00 Asia/Shanghai
（04:00 UTC）恢复**。本节覆盖下方所有旧“继续/下一步/每小时推进”指令；期间不启动
下一轮开发、实验、模型/数据库调用、训练、baseline或远程轮询。Goal整体尚未完成，
保留active目标，不将暂停误记为complete/blocked。

真实FinBench SF0.1新120组已由49aaff0代码一次离线构建并核验，24开发/48训练/48评价，
每类40；NL、独立CSV答案与gold隔离，361个文件校验值通过，旧锚点/近重复与跨split
组复用检查通过。耗时5.400秒，零模型/数据库/fit/方法运行。评价组33空/15非空，
直接转账组40题全空；必须分组报告，不能重抽题改善结果或只用总体EM讲准确性。
[本轮进展与边界](report/finbench_one_shot_population_20260912.md)。

恢复后才准备真实serving profile/catalog/statistics、同事实RDF和共同评分/资源预算；
正式campaign_ready仍false。核心已通过的NL→估计选择→真实双库答案继续接受，不重跑。
外部baseline只保证忠实可运行、如实报结果。Sep14 17:00/Sep18目标保持。

## 以下为前序进展，执行时间受上方最新门限约束

金融普通NL真实链路已在03314a9通过：一次qwen3.8-27b调用（1928输入/550输出token），
紧凑意图确定性编译、冻结catalog预测绑定、六个合法计划按估计选一个，执行Neo4j6次+
Fuseki3次，答案账户2=66、账户3=9，与独立reference完全一致。核心在线3374.613ms；
零probe/训练/fit/retry/baseline调用，服务已停止、输入封存未变。[完整证据](report/compact_financial_nl_20260912.md)。
六项新provider/录制/模式/模型兼容检查通过；未重复此前九项lowerer检查或旧成功门禁。
该结果是一个曝光开发题的performance集成证据，不是完整金融NL准确率或baseline提速。
路径/风险排名有独立小图和冻结估计证据，实际compact模型质量待正式评价。旧v1/v2/v3
[失败与成本](report/financial_nl_20260912.md)原样保留，不调prompt修该题，不替baseline修结果。
下一步冻结批准的真实FinBench/RDF样本、独立reference、数值等价和预算/split契约，
补必要共同输入适配后执行主评价；消融在后。Sep14 17:00核心、Sep18真实结果目标不变，Goal active。

前序输入证据：FinBench同事实离线映射已实现；8实体/16关系小图上的三类查询
在真实Fuseki各执行一次，独立答案均exact。该轮没有LLM、baseline、训练或大数据调用。
当时缺失的边属性访问和字段/时间比较现已实现并完成上方确定性双库验证；金融NL待验收。
[前序结果](report/finbench_rdf_tiny_20260912.md)；[表示契约](decisions/finbench_same_facts_rdf_v1.md)。

最新原则：baseline只要能运行并如实记录，不替它修算法、补语义或优化成绩。
FedUP/FedX已在双源9事实tiny图运行；FedUP排序错误、聚合失败保留，不是待修复门禁。
外层Jena补全尝试已撤出；后续工作回到XGAP的FinBench输入/reference与正式评价准备。
[接入结果与成本](report/external_federation_tiny_20260912.md)；[baseline原则](decisions/baseline_fidelity_v1.md)。

## 当前进展：有界核心与通用评价入口已达到实验方案讨论门槛

普通NL-only真实拆分链已验收：一次模型解释、估计选出一个计划，Neo4j与Fuseki各
执行必要子查询，独立预期答案exact；首次Interpretation失败保留。新通用接口已实现
冻结数据集/源/schema/catalog/model/模式配置、逐请求持久记录、严格离线replay和
结果封存后独立评分。9项不同的新风险检查及一次CLI预检通过，本轮外部调用为0。
[核心逐项验收及边界](report/one_shot_core_freeze_20260912.md)。

有界research backbone已实现并有集成证据；正式实验、外部对照与精度/提速结论尚未
完成。[18图讨论稿](research_experiment_proposal_20260912.md)及
[外部方法核实表](report/external_comparators_20260912.md)现已完成，逐图明确RQ/X/Y、
population、成本与可比外部方法。用户已批准建议优先级；机器清单进入priority_approved_protocol_finalization，campaign_ready=false。
本轮仅核实公开文档与本地artifact状态，零新模型/数据库/训练/实验运行，无代码回归。

建议优先FinBench原生与同事实RDF的FedUP/FedX，提前有界FedShop外部验证；GrailQA
及KBQA-R1/o1保留为待完整KB/模型条件的对照轨，不取消原目标。该优先级调整已由
用户批准，不再重复确认。现在锁定FedUP/FedX版本、薄适配及真实数据/reference/预算；
正式campaign先满足这些具体门槛。继续tiny开发，不重复失败下载或已通过核心门禁。核心Sep14 17:00和真实
结果Sep18目标不变，整体Goal仍active。下方旧阶段安排仅作历史。

## 用户补充：估计器以选对计划为目标，不要求精确回归时间

cost estimator可以预测相对快慢、偏好或可比较的排序分数；准确预测毫秒值不是核心
完成条件。优先评价排序质量、选中计划相对声明候选域最优计划的regret，以及总在线
成本；时间回归误差仅为可选诊断。参考最优只能在后续独立离线评价中测量，不能成为
每次在线选择的探测步骤。现有v2毫秒模型继续作为一个可用实现，不为降低回归误差
重复训练或重跑已通过门禁。纯排序输出接入时需显式声明单位、跨解释可比性和质量
权衡规则，不把无量纲分数当毫秒，也不沿用未经满足假设的2η时间regret界。
见[更新后的选择契约](decisions/one_shot_modes_v1.md#selection-oriented-estimation--user-update)。
拆分小图与普通NL-only闭环现已通过；日期和一次执行约束不变。

## 最新推进：估计器v2与真实跨库确定性链已验收

28个独立小图训练计划全部完成（46次后端调用，另有2次常量warmup）；非负模型离线
拟合/冻结后，新排除查询只执行1个选中计划，Neo4j/Fuseki各调用1次，答案与独立预期
一致，全程零LLM、零当前题探测/在线fit。5项新风险检查通过，旧模型和434份输入不变，
服务已停止。[证据](report/work_estimator_native_20260912.md)。预测9.524ms、实测18.695ms
是单个已覆盖模板内的排除查询，不是泛化/提速证据，不能与旧B01直接计算提升倍数。

下一步集中于真正拆分的tiny数据，以及不预置operator IDs/结构化约束的普通NL-only
请求。当前已验证真实跨库执行，但两库数据还是副本；本轮输入是声明语义程序，未测
LLM理解。旧真实模型precision答案保持接受。28条新训练/5项检查/这条成功请求不重跑。
9月14日17:00核心验收、9月18日真实实验目标不变；Goal继续active。

## 最新里程碑：首个带显式约束的真实 one-shot 答案已通过

用户批准的Goal继续active。41a3cca以一次外部LLM请求完成B01解释、冻结catalog
绑定、估计选plan和一次最终执行；2次Fuseki调用返回1条结果，与独立gold完全一致。
没有当前题探测、在线训练或自动重试；复用了先前四条独立训练的冻结模型。
精度/性能两模式的受控骨架均已接线；真实成功目前仅是precision的一个带显式约束
小图请求，不能宣称完整系统、跨库执行、模型准确率或提速已经得到证明。

下一步按优先级：补operator×backend/工作量特征，独立于当前请求补tiny训练覆盖
并处理外推；准备一条
Neo4j与Fuseki各承担必要子查询的极小联邦vertical slice；补一条没有预置operator IDs/
结构化硬约束的自然语言请求，验收performance输入预算和结果标记。保留已成功的
带约束slice，不重复跑它或64项已有新增风险检查。只验证新边界，不做消融/大数据。

当前四条Match-only训练不足：本次选中计划预测0.0054ms、实际scheduler约78.93ms，
不能作为有用估计器或效率优势的证据。先补代表性训练及明确外推策略，不用当前
B01结果偷偷训练。前三次失败原样保留；[完整结果与范围](report/one_shot_native_20260912.md)。
9月14日17:00核心验收、9月18日真实实验目标不变；核心验收后再讨论16–20张图。

## 9月12日首个执行检查点

新one-shot普通入口已完成受控小图闭环，两模式都返回独立预期答案；解释、grounding、
真实策略、冻结估计器与一次最终执行已经接线。48项新增风险检查通过，详见
[实现证据与边界](report/one_shot_core_20260912.md)。这些是开发检查，不是新FinBench
实验或真实模型准确率。下一步是新入口的实际LLM+Neo4j/Fuseki小图验收与必要估计器
完善；继续按批准计划推进，不重复成功门禁、不开始新消融。

## 当前权威目标：9月12日用户批准恢复，48小时打通 one-shot 双模式

用户已批准方案并要求立即执行。本节覆盖下方所有历史暂停与下一步安排。
XGAP是研究原型：在明确语义边界内，以同一普通入口实现精度/性能两模式、
有界top-K解释、真实物理策略、冻结估计器和Ptime联合选择，然后只执行最终计划。
不通过当前问题试跑全部计划选优；允许显式标注的解释/召回近似，保留硬约束、
真实失败和未知成本。catalog等离线构建并冻结，单列一次性成本及摊销。

执行目标：北京时间2026-09-14 17:00前完成核心联通与评价接口，9月18日前真实实验。
严格toy-first；骨架一致接通前不开展新消融/基线比较/规模扫描。完成后讨论16–20图、
明确RQ/X/Y及同图外部SOTA。见[批准契约](decisions/one_shot_modes_v1.md)和
[48小时执行计划](one_shot_development_20260912.md)。核心接线与首个带约束真实答案已验收，
其余核心边界仍待完成，不能宣称完整系统已验收。
旧FinBench成本负结果与LINK3/5继续保留，不冒充新系统结果。

## 以下为历史记录，优先级由上述批准目标覆盖

## 9月12日本轮完成；按用户要求暂停，先讨论下一步

用户明确要求：获得本轮结果后暂停开发和实验，先汇报进度、结果与改进策略。
现有 heartbeat 已暂停；不要执行下方历史“下一步”或旧时间恢复计划，等待用户恢复。

原 FinBench48 × 六轮 × 三个 prepared-plan 方法的864次最终执行、576次采集全部
exact，2880查询调用，零模型调用。原32题 paid/hash=3.262、paid/bind=2.601；
原16题仅描述为1.846/4.650。完整试跑选优没有降低总成本，不能称P1/A3已有提速。
[本轮报告](report/finbench_paid_balanced_20260912.md)保留所有人口、曝光、成本与范围。
日志热路径修复和12项新增风险检查已验收；一次native95.585s，双库服务已停止。
尚缺真实策略空间接入P1/A3、实际prior/forecast成本与校准、E1/E3–E5及外部对照证据。
小图优先与9月18日真实实验deadline不变；当前仅收尾报告，不启动这些后续工作。

当前权威更新（9月12日）：真实FinBench三题成本集成已完成。fixed hash、fixed bind、
付费双计划选择共9次最终答案和6次采集答案全部exact，30次查询调用、零模型调用；
原48题及32seen/16heldout完整保留，三题均integration-exposed，其余45未测。
14项新增检查首次通过、一次native运行与23项证据审计通过，服务已停止。见
[真实付费选择证据](report/finbench_paid_pilot_20260912.md)。本次发现累计完整台账写入
干扰方法wall，尚非正式性能结论；下一步只修每次结果单独保存、小型进度/选择索引和
显式持久化计时，再冻结原48题的题内平衡重复块。不能事后扣掉估算开销、重跑已验收
pilot或把两个策略伪装成P1 source replicas。真实P1/A3接线、prior成本和E1–E5仍待完成。

外部LLM已连通；Match行约束保留原语义编译。原五份v3录制中B01/B04/B05真实
Neo4j/Fuseki答案正确，B02/B03解释失败，严格3/5且五题终态完整；不是五题全对。
见[真实五题闭环证据](report/match_row_link_20260912.md)。不等待模型100%成功才进行
独立规划实验，保留所有历史失败/分母与9月18日真实评价deadline。

历史外部LINK：用户提供的外部qwen3.8-27b服务已连通，五题真实生成与解析通过；B01已
经普通catalog/P1和真实Neo4j+Fuseki执行，但多返回age列，严格答案失败，四题原生
未运行。复用已保存响应定位输出结构，不改gold、不重复模型/失败原生动作；GPU等待
已不是这条路线的阻塞。见[外部服务与实际执行证据](report/external_toy_link_20260911.md)。
外部接线已验收，完整LINK及真实评价尚未完成；3804210保持用户更新的独立作业。

更新：2026-09-11，依据用户明确指令。本文是现有 active Goal 的权威开发补充，
覆盖旧 roadmap、status、报告和 automation 中冲突的开发优先级；保留所有历史
结果和已冻结的最终评价协议。当前第一要务是快速完成系统，修复实现与设计不匹配之处。


最新输入与结果（9月11日晚）：原始FinBench source/workpack和3804011五题记录均已
本地核验。真实SF0.1固定3题/6计划全部exact、107项审计通过，服务已停止；这是
prepared-query integration，不是完整48评价或普通P1/LLM实验。实际模型5次调用
产生的程序原样走普通链完成0/5，失败已保存；结构准入已收紧，v2 prompt准备好但
新生成质量未测。下一步模型v2小验证、真实prior forecast/成本来源、gold-blind
答案投影和冻结E1–E5，不重复索取已到文件/跑成功门禁。详见
[INT-3](report/finbench_original_three_native_20260911.md)与[LINK](report/qwen_model_link_failure_20260911.md)。

后续进展（同日晚）：3804210已由用户确认PENDING(Resources)、运行0、未分配节点；
用户有变化会告知，不重复查询或提交。INT-4执行侧通过16项小图检查；E1-A再用独立
版本补上推理拥有的答案位置，经过原grounding/语义排序/P1返回类型化实体答案，
23项新检查首次全部通过。见[推理答案闭环证据](report/inferred_entity_answers_20260911.md)。
这是controlled HTTP与tiny RDFLib的接口验证，真实模型质量、真实facts/scoring与
公平E1–E5仍待完成；ε不保证答案位置正确。原150 runner仍semantic-only，原150/48、
FinBench integration-exposed标记、模型0/5及真实FinBench6/6保留。08e4b3b包不改。


最新E1-B/INT-5：独立实体答案EM/F1与失败/未运行/未知成本记账已接好，18项新增
检查首次通过；原150参考格式可用但150全部not_run，无准确率结果。找回了既有
query-independent首shard事实，完整哈希核对并迁到持久INT-5目录，24文件约436MB；
这仅1/964，不能宣称覆盖GrailQA全库。见[评价与事实证据](report/entity_answer_evaluation_20260911.md)。
下一步是真实数据覆盖、模型输出、真实prior成本与公平实验，不再重建已保存facts。

## 总目标

**最新优先级：一切工程由research question和实验计划驱动。** 权威工作计划为
[RQ、X/Y因素与实验计划](research_experiment_plan_20260911.md)，算法约束为
[Ptime planning与解质量界](decisions/planning_ptime_contract_v1.md)。先定义问题、
贡献机制、efficiency/effectiveness/scalability的X因素、Y指标、强对照、消融及
完整性验收，再实施对应工程。不能把XGAP变成无限建设的通用开源项目。
算法必须可描述并给出输入规模、目标、伪代码、Ptime复杂度；greedy/heuristic须
给出有假设的解质量界。候选上限、timeout和经验提速不等于近似保证。当前主入口
的组合枚举已由P1的局部选项路径替换，见
[实现与首个负结果](report/polynomial_planning_20260911.md)。终端source独立性判定
已修正，P1当前范围验收完成：29项定向检查、150个受影响成本表回放、70个旧oracle
全部匹配；原6.33倍regret保留并修复为1。见
[修正与下一步](report/polynomial_terminal_correction_20260911.md)。A1已接通普通入口的有界acquisition与
pre-execution reselection；三种实际行为、小图gold、历史/当前成本和失败处理通过
定向及真实小图检查，见[A1证据](report/semantic_refresh_20260911.md)。一次观测中
不刷新最快，不能声称收益已成立。A2现已接通execution-prefix adaptation的残余
计划/复用约束：完成的source固定，只重选未完成部分，定向及真实双库小图验收通过；
见[A2证据](report/semantic_prefix_20260911.md)。该次固定顺序观测中不重规划更快，
不能把成本模型下降说成实际提速。A3已加入单请求的预测净收益/预算停止规则，
逐预测情形使用相同initial baseline，给出条件decision-regret界并通过定向验收；
见[A3证据](report/semantic_acquisition_20260911.md)。规则可调用不等于预测已校准或
实际收益已成立。INT-0已恢复原150题的7个必要输入文件，字节/SHA全部匹配；
固定两题已定位普通Traverse与既有raw-RDF/Neo4j mirror间的编码适配缺口，
见[真实输入恢复证据](report/real_input_recovery_20260911.md)。INT-1表示适配已在小图
实现并通过双库验收，见[编码接线证据](report/resource_triple_encoding_20260911.md)。
A4现已实现离线经验forecast准备和当前环境/原请求来源校验，普通入口与成本切分通过
定向验收，见[准备接口证据](report/semantic_forecast_preparation_20260911.md)。真实先验
数据和校准仍缺证据；旧A1数据不重标为training。FinBench有界原包收集工具已备好，
下一步取回真实facts/load记录及FinBench原包，接独立答案和真实forecast来源；
scalar comparison在该新adapter仍显式不支持，保留原10题及150总分母，不扩展catalog。
不能把单步刷新/残余重选/模型决策当成整个agent完成。
模型LINK和真实数据评价仍待完成。不能把“有有效界”说成“真实延迟近似最优”。

**最新工程标准（2026-09-11）：XGAP是research prototype，以保证论文实验结果为
核心要求，不追求完美实现。** 优先正确性、可复现、公平对照、全部失败/样本分母和
真实成本。只建设支撑明确research story和待测方法所需的能力；通用streaming、
产品级UI、任意分区发现等不能自动变成实验前置条件。已有代码优先复用和接线，
不为“完整”持续扩充框架。边界明确报告，缺少某项扩展不等于整个原型不能评价。

**最高优先级 deadline（用户于2026-09-11明确）：一周内得到真实实验结果，
最迟2026-09-18交付；内部收尾目标为当日12:00北京时间。** 完整系统目标不变，
但本周先交付真实数据、真实模型与真实后端的可复现实验、对照、质量/端到端成本和
失败分类。已完成的toy/replay、旧实验或catalog覆盖率不能替代这次新真实结果。
冻结现有查询范围与实验协议，所有样本保留终态和分母；不以成功题筛选掩盖失败。
当前接口改动收尾后立刻转实验关键路径，UI、非必要扩展和大catalog重建后移。
**后续明确补充：快速开发验收未完成前，不在服务器运行大数据集。远程运行只允许
用小图/少量问题检查模型健康与各环节联通。先完成小数据全链路，再开展真实数据
实验；deadline不能成为提前跑大数据debug的理由。**
模型/GPU/远程访问的实际可用性提前验证；H100优先且允许已授权的兼容fallback，
不能因等待单一型号而耗尽一周。需要用户凭据/服务器动作时立即给出具体最小动作。

持续将 XGAP 建成可用于 SIGMOD 级实验的完整 agentic federated graph query
system，包含正确的语义、确定性规划/编译、真实 Neo4j/Fuseki 可插拔执行、可选
LLM interpretation、离线数据/catalog/ontology 准备、可复现实验及必要轻量 UI。
按明确 milestones 循环设计、实现、测试、实验与复盘。只有凭据、VPN/必要人工
服务器操作、外部 artifacts 或实质研究方向决策需要用户介入；此次 toy-first
方向调整已获明确授权，不重复确认。

## 本次暂停与恢复

**已恢复：2026-09-11 10:15 +08:00 核对时间及 clean d9c2858 后继续工程。**
现有 xgap heartbeat 已恢复每小时节奏。以下是已履行的历史暂停要求，
不能再据此暂停后续开发。

用户于 2026-09-10 晚明确要求：完成当前 T1 capability milestone 后暂停开发，
北京时间 **2026-09-11 10:00** 恢复。期间不启动新 milestone、实验或无意义轮询。
现有 xgap 定时任务已调整到下一次上午 10 点，恢复时还原此前每小时持续节奏。
这是用户指定的暂停，总体目标仍未完成，不标记 complete 或 blocked。

## 开发原则

1. **Development dataset 可以是自己构建的极小 toy graph。** 用于快速测
   correctness、接口、planner、semantics、compiler、execution，以及快速 debug
   和迭代。开发进度以完整系统正确工作衡量，不以跑通 GrailQA 衡量。
2. 先准备一个极小图和十几个 query，初始目标约 16–18 个，覆盖核心 operator。
   每题必须有完整预期链：

   **NL → gold PathPatternQuery → expected logical plan → expected target query
   → expected result**。

   对不能由单个 PathPatternQuery 表示的顶层 Join/GroupBy 等操作，显式补上
   semantic DAG wrapper 和 path 子查询；不能把整个查询系统强行降格成 path IR。
   图、问题、类型化答案、计划和目标查询都应小到能人工检查。预期答案独立于待测
   实现编写，不能直接把当前实现输出存成“正确答案”。
3. 第一阶段可以 **skip LLM**，把 gold 语义 fixture 直接输入确定性链，证明
   XGAP backbone 工作正常。这是合法的 toy 模块/集成测试，不是自然语言准确率。
   大数据集推理仍保持 gold isolation；不将评价实体补入 inference catalog、
   排序器或部署事实。
4. 永久维护两条独立测试链：
   - **Interpretation**：NL 与允许上下文 → 候选/选定语义，与 gold meaning 和
     硬约束对照。固定 provider 响应用于接口测试，真实模型质量单独验收。
   - **Deterministic planning**：固定语义 → logical plan → target query / native
     fragments / federated plan → execution → expected typed result。不得依赖
     LLM、GrailQA 原始语料或 catalog build。
5. **模块隔离测试＋永远维护一条完整 vertical slice。** 每次相关修改后，最小
   toy E2E 必须仍能工作。局部测试全通过不代表系统完成；核心设计中尚未支持的
   算子/组合必须明确列为缺口并修复，不能用“显式拒绝”冒充已经支持。
6. **GrailQA 不是开发环境。** 不集中力量追逐高成本 benchmark 的各种小 bug。
   Toy backbone 跑通之后，才用小型冻结的 GrailQA-mini 检查真实集成。Full
   GrailQA 和其他大数据集只负责最终真实评价、规模实验、baseline 与消融比较。
7. **GrailQA catalog build 与 runtime 彻底解耦。** Build 是显式 offline
   preprocessing；成功后 freeze/version。Runtime 只能读取/查询准备好的 artifact，
   不能扫描语料、重建、自动下载或隐式生成 catalog。缺失/不兼容时清楚报出准备
   条件；后续有意 rebuild 必须产生新版本并保留旧版本。
8. 构建 **failure replay**：保存最小复现输入、相关版本、model/tool/backend
   observations 和失败边界，用本地确定性回放代替重复高成本运行。回放证据与真实
   外部运行分开；不得静默重试失败的外部动作。
9. 节约开发时间与 token：每次检查须对应实验阻塞或具体失败风险，只跑相关
   targeted tests＋tiny vertical slice。**milestone不再自动触发broad suite**；
   只有共享核心改动、未解决的回归风险或冻结的实验发布计划能说明必要性时才跑。
   文档修改不跑软件回归；同一成功无新变化不重跑。模块测试不以GrailQA成功为
   门槛。不为抽象完备添加无当前实验必要性的guard、审计层或协议框架。

## 测试阶梯

| 层级 | 责任 | 不能替代什么 |
|---|---|---|
| Toy E2E | 保证整个系统能跑、受控语义能得到正确结果；LLM 可跳过 | 真实 benchmark 准确率/性能 |
| Module tests | 保证局部语义、接口、planner、compiler、execution 正确且可快速回放 | 完整组合链的正确性 |
| GrailQA-mini | 以冻结小样本和预建目录保证真实数据/服务集成 | 官方全榜或完整评价 |
| Full GrailQA 与其他大数据集 | 真实评价、规模、baseline、消融 | 日常开发/debug 环境 |

保留 FinBench、GrailQA 两个已选主数据集和原 EQ1–EQ5 最终评价义务，不围绕通过
的 toy cases 重写研究问题，也不将 toy、replay 或部分 shard 当真实 benchmark 结果。

## 下一组 milestones

- **T0：最小图与完整 query fixtures。** 明确身份、typed scalar、方向、多步路径、
  重复/循环和空结果，给出等价 Neo4j/Fuseki 编码及联邦 placement。覆盖 Nodes、
  Edges、Selection、Union、Join、Projection、GroupBy、OrderBy、Recursive 及
  对应 path modes/SHORTEST；具体组合冻结后逐一列出 expected chain。先交付不需
  模型或大语料的第一条完整确定性 slice。
- **T1：确定性 backbone 与设计缺口。** 用真实 planner/compiler/runtime 跑全部
  fixtures，对照独立参考与小型真实数据库。交付 operator-by-layer 覆盖表，修复
  具体缺口，每次修改保持 tiny slice。验收依据是正确行为，不是测试数。
- **T2：Interpretation、catalog 边界与 replay。** 同一 fixture 集验收 interpretation
  接口及语义；独立 offline build/freeze 与 runtime read-only lookup；证明 runtime
  不会调用 builder，并离线复现已有失败，不重跑外部动作。
- **T3：真实小集成，然后最终评价。** Toy backbone 正常后，接入 GrailQA-mini、
  真模型与真后端；最后才开展冻结的大数据集 baseline/消融。UI 复用同一接口。

功能验收可以排期，正面效果、memory 优势、ontology 收益或 SIGMOD 录用不能承诺。

## 当前进度与被替代的工作

- **T0 已验收，图与 gold 保持冻结。** 5 节点、8 边、18 道完整 path gold chain；
  新增 8 个语义组合 fixtures。真实 Neo4j/Fuseki 路径执行 36/36、语义组合 8/8
  和原两后端 vertical slice 已通过。历史 M5 IN 缺口在本轮方向扩展中闭合，
  当前显式版本化逻辑预期与答案均 18/18；原始 gold 文件仍保持冻结。
- **T1 的规划连接步骤已验收。** 从一份语义和显式逻辑数据源副本声明自动生成候选，
  复用唯一源观测，经既有代价选择器选型，再执行选中计划。真实 gate 8/8 程序、
  28/28 候选答案正确；106 项 focused 通过。Broad acceptance 原 session6473
  已 exit0：3,069 pass/38 skip，24 个 harness/example 入口通过。此规划连接步骤
  已验收，完整 T1 仍在进行。
  新入口不是任意 source discovery 或 Traverse 内部自动跨库切分；没有 snapshot
  时会 profile 所有唯一源片段，其代价已计入，不宣称规模优势。
- **T1 语义绑定/控制连接已通过真实 gate。** 唯一候选通过类型化槽位进入实际
  身份/条件/schema/source，命名结构化约束与原条件取 AND；既有 GoalLoop 接到
  规划与执行。新增 5/5 查询、18/18 候选答案、10/10 独立原生对照和旧 slice
  正确；新模块29 pass、兼容57 pass。Broad acceptance 原 session11079 已
  exit0：3,098 pass/38 skip、24 个 harness/example 入口通过，此连接步骤已
  验收。真实模型理解仍未验收；原 graph/gold 均不变。
- **T1 方向扩展通过真实 gate。** 独立设计 Reverse 保留 Edges(G)、边身份和
  递归规则，支持 IN 逻辑参考与有界 UNDIRECTED 原生展开。九题双后端 18/18
  编译答案、18/18 独立对照和旧 slice 正确；focused212/最终fast272 pass。
  完整回归原 session96124 已exit0：3,117 pass/38 skip，24 个 harness/example
  入口通过；此方向步骤已验收。见 [方向报告](report/toy_backbone_t1_orientation.md)。
- **T1 capability 准入已验收。** 非空要求现在对应
  当前操作实际生成的 native/coordinator 节点。八个已有完整链的显式 overlay
  保留 16 个位置、按预期排除 12 个；真实 8/8 查询、16/16 候选答案和旧 slice
  正确。Focused120/daily300 pass，完整回归原 session91696 已 exit0：
  3,145 passed/38 skipped，24 个 harness/example 入口通过。见
  [本轮报告](report/toy_backbone_t1_capabilities.md)。
- **T1 Optional/有限重复已验收。** 用已有代数表达次数范围，保留最短选择
  的作用域与零路径区别；13 道新完整链，真实双后端 26/26 编译答案、26/26
  独立目标及旧 slice 正确。Focused226/interface42/daily335 pass；完整回归
  原 session81593 exit0：3,180 passed/38 skipped，24 个 harness/example
  入口通过。旧 gold 不变，见 [有限重复报告](report/toy_backbone_t1_repetition.md)。
- **T1 有限嵌套作用域已验收。** 普通 Traverse
  入口组合原生子路径与 coordinator 拼接/递归，保留局部最短和外层过滤顺序。
  15 题双后端 30/30 程序、30/30 独立目标正确；当前规划 3/3 程序、6/6
  候选和旧 slice 正确。原生首轮的本地比较异常、最小回放、准入补丁与补测
  边界均见 [嵌套作用域报告](report/toy_backbone_t1_scoped_paths.md)。最终 daily358
  通过；完整回归原 session71124 exit0：3,203 passed/38 skipped、24 个
  harness/example 入口通过。完整 T1 与 T2/T3 仍未验收。
- **下一步**：继续同一 toy graph 的剩余 native/typed
  semantics，并推进 T2 Interpretation、offline catalog freeze/runtime-only lookup、
  failure replay，再进入 T3。详细 evidence 见
  [当前工程状态](engineering_state.md) 和 [方向闭合报告](report/toy_backbone_t1_orientation.md)。
- D205 的 provider＋真实后端是受控接口结果，不是真实 LLM 准确率。D207 GPU
  健康检查软件已验收，但最新真实部署仍未产生模型答案；GPU 不阻塞 toy 工程。
- D208 大 shard CPU 测量已在启动前延期，保留 runner，native campaign 未执行。
  catalog 8＋4＋1 与 GPU 历史诊断保留在报告，不再占据日常开发首位。
- 历史完整数据、负结果、FinBench/GrailQA 与 EQ1–EQ5 最终评价义务均保留。
  新 toy 进展不能替代正式效果；完整系统 Goal 仍未完成。

## 新验收：原生布尔条件

2026-09-11：现代 Match 与有限路径执行的 AND/OR/NOT 已验收，保留缺失属性、
既有标量相等和 SHORTEST 外层过滤语义。独立属性 overlay 有20条完整路径链与
4个类型化Match程序：真实40/40路径＋40/40独立目标、8/8Match＋8/8独立目标、
3/3规划程序/6/6候选及旧联邦slice正确。补充Match准入gate通过，最终生成计划
与已执行记录48/48完全一致。日常401通过，完整回归3246通过/38跳过，24个
harness/example入口通过。历史失败和源码版本边界保留在
[专项报告](report/toy_backbone_t1_boolean_conditions.md)。

下一项仍按同一toy推进typed聚合/排序与剩余路径覆盖：当前大整数SUM精度、RDF
数值输入和nullable排序已有最小本地观察，需要明确binding类型约定后修复。
原始代数不变，T1整体及T2/T3仍未验收；catalog/模型/大benchmark不成为本步前置。

## 新验收：binding 类型、聚合与排序

2026-09-11：共享 binding 值规则完成精确整数/decimal求和、COUNT(field)/DISTINCT、
分组与连接数值等价、空值排序及原生RDF数值验证。15条独立完整链，真实15/15程序、
32/32候选答案、27/27独立目标和旧双库slice正确；声明core/credit属性视图，不假设
Neo4j拥有任意精度decimal副本。日常489通过＋18题演示，最终完整回归3334通过/
38跳过，24个harness/example入口通过。分项失败、参考语义差异及补测边界见
[类型语义报告](report/toy_backbone_t1_typed_bindings.md)。本步骤已验收，整体Goal仍active。
下一步按下方用户澄清先收口有限profile及范围内缺口，再进入T2，不无限扩充查询语言。

## 支持范围先行，而非无限扩充语义

2026-09-11 用户明确提出：XGAP 可以限定支持的查询语义并给出 bound。
Interpretation 的 NL→语义表示，与 operator/compiler/runtime 的可表达性和
正确性分开验收。先明确一个有限、独立于编译器成败的查询 profile，再修复范围内
的实现缺口；范围外类型明确说明，不把“支持所有查询”当作系统完成标准。
现有数据集和研究评价义务保留，不能在看过结果后缩小范围以隐藏失败。
当前能力、实际代码上限和建议工作负载 bound 见
[范围说明](decisions/bounded_system_scope_v1.md)。其中建议的小 L 不是已经安装的新
全局限制，新的论文适用范围仍须在评价前明确。

## 新验收：通用问题入口与解析回放

2026-09-11：T2-B把受控NL解析、可执行硬约束、固定目录绑定与正常规划/执行连接
到同一入口；独立解析链仍可单测。真实5/5程序、18/18候选、10/10独立目标及旧
slice正确，最终focused77通过；完整回归3394通过/38跳过，24个harness/examples
入口通过。Provider响应/失败可离线回放，但不声称真实NL质量或通用backend回放。
下一步直接接真模型到同一小图入口，远程仅做小数据联通。遵守9月18日硬截止，
小数据开发验收前不得运行服务器大数据集。见[本轮报告](report/toy_backbone_t2_interpretation.md)。

## 新验收：真实模型适配接口，实际模型联通待执行

2026-09-11：T2-C单次模型HTTP适配、精确token预算、未知usage标记及失败记录
接入同一小图入口。本地focused157/114通过；记录回放至真实双库5/5程序、18/18
候选、10/10独立目标及旧slice通过。完整回归3421通过/38跳过，24个入口通过。
这仍是受控接口证据，真实Qwen响应尚未取得。新远程入口最多5题/5次生成、1小时，
只做模型与小图联通；开发验收前禁止服务器大数据执行的用户要求保持不变。
见[模型接口报告](report/toy_model_interface_20260911.md)。下一步取真实响应接同一
小图，不再扩充通用框架；9月18日真实实验截止及全部评价分母仍保留。

## 新进展：无观测物理对照与小模型任务实际提交

2026-09-11：T3-A在同一问题/绑定/编译/执行入口加入显式固定后端优先级，供后续
比较规划观测的成本是否值得；默认costed策略不变。Focused115及真实双库5/18/10
和旧slice通过；最终完整回归75266退出0，3457通过/38跳过、24入口通过，已验收。
这里只是小数据correctness/成本核算
验收，不替代本周真实数据实验。见[本轮报告](report/static_semantic_selection_20260911.md)。

用户已实际部署固定bc2bb67。H1003803984在排队时取消且运行0；已授权的双L40S
替代作业3804011已提交，PENDING/Priority，预计北京时间今天18:28:27启动，最多
5题/1小时，关闭自动requeue、排除gput069。真实响应
仍待取得，再接回同一小图执行。既有小数据优先规则和9月18日真实结果截止不变。

## Goal 工具状态

有限查询契约已具体化为 [bounded query profile v1](bounded_query_profile_v1.md)：
列出算子、类型/空值、有限路径、显式source/identity、范围外语法及逐层证据。
查询语言范围、运行资源预算、最终benchmark覆盖率分别报告，不能互相替代。
当前T2-A将小catalog、typed bindings与可选ontology离线冻结为同一版本；新通用
agent入口只读调用方固定版本，不扫描原始数据或隐式重建。验收和剩余legacy迁移
见 [T2-A报告](report/toy_backbone_t2_frozen_resolution.md)。

当前应用 Goal 工具支持创建、读取及完成/阻塞状态更新，不提供活动目标正文编辑。
现有总体 Goal 保持 **active**，未假装完成或重新创建。本文、AGENTS 必读规则、
engineering state 与现有 heartbeat 共同持久化新的执行依据；应用中旧 Goal 文本
不能覆盖这条后续明确用户指令。
