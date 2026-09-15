# 部分绑定共同前端与外部组合方法

2026-09-15。实现完成；真实共同输入门尚待执行。本报告随本次验收更新。

问题：旧FedUP/FedX路径消费完整SPARQL或旧NL输入，不能直接作为新trusted-template
strong系统的同信息权限对照。现在新增显式`fixed-info-{exact,performance}-{fedup,fedx}`：
固定信息动作顺序→共享权限/typed绑定→一次global SPARQL编译→原作者方法执行一次。
没有修改FedUP/FedX算法、global compiler、支持语义、答案或按结果调参。

EXACT仍要满足权威绑定，PERFORMANCE可采用当前profile授权的预测。固定前端复用
strong域的绑定admission，但不构造XGAP物理候选，也不声称自己的动作序列是strong
policy。声明内工具失败可走预定后续；非法/未声明结果、越预算和编译失败直接保留。
模型未报告的成本保持null；资源reservation另列，不能计成实际用量。

新v2 study显式列方法，按预先组号轮换方法顺序。旧v1和旧NL/RDF清单不变。调度复用
common trial、guard、observer、post-seal score和journal；参考答案不会交给部署/端点/
资源回调。每个方法只计自己的owned host及共同source，不把别的闲置host计入该方法。

定向检查覆盖同输入两权限、真实RDFLib求值、失败分支、未知/非法/越额成本、编译
不支持、原生错误答案/超时不修补、mapping pin/搬移、v2顺序/续跑、host监督和旧分母
隔离。17个新增case最终通过；另检查受影响的strong权限、worker和v1 study路径。
首次所选运行3 failed/11 passed：两处测试gold的URIRef与既有编译器STR返回类型不匹配，
一处测试没有创建搬移父目录。仅修正测试设置，重跑这3项为3 passed；未改答案或编译。
之后只检查新加入或直接受影响的边界，未跑全套回归。

实际前的元数据预检：`fixed-information-preflight-20260915-v1/receipt.json` SHA
`4f2559e9429cebe723a90f7ba99ed87b0272852f2fe10c8add3e1580d1a30537`。
六方法共享一个类型hole输入、一个故意错误的预测和同一权威回答；0模型/源请求。
预期EXACT读权威回答得到Account，PERFORMANCE可以采用Person预测。gold为既有
tiny fixture的Account business IDs 1/2/3/4，独立于方法输出；这不是随机质量样本。
使用既有冻结tiny RDF/TDB和FedUP summary，不重建catalog、不训练估计器。

代码：`agent/fixed_information_frontend.py`、`experiments/fixed_information_worker.py`、
`practical_methods.py`；共享binding extraction、profile mapping pin、worker/common/study
路由；`scripts/check_fixed_information_tiny.py`仅封装一次必要新边界，不是新的通用harness。

RQ：相同输入权限下，联合strong信息/物理规划相对固定信息流程加成熟联邦planner，
是否降低query-to-answer成本并改善正确完成？X为方法/模式及预先声明的信息预算；
Y为正确完成、online时间、获取/模型/源成本与失败种类。本轮只验证工程接线。

MaterialPassport：用户授权的研究比较集成；可信有界结构；模型0次；合成开发输入；
非开放NL、非真实准确率样本、非速度结论、非论文profile发布。d仍metric_deferred。
下一步是具体部分绑定population/模式配置/release验收，然后主评价，不是更多旧门回归。
