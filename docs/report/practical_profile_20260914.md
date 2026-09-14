# Strong 模式冻结配置与普通请求记录入口

2026-09-14。在`abb6fba`之后完成；源文件SHA见证据索引。此次是工程一致性门，
没有新增真实模型或数据库调用，也没有做消融、baseline修改或大数据集运行。

EXACT/PERFORMANCE现在通过同一个冻结配置和普通请求入口执行：可信模板、请求绑定、
预测、工具顺序、信息预算、物理预算、冻结估计器与源版本均有明确配置及校验。
支持显式发布、预检、执行记录及离线回放。[契约](../decisions/practical_profile_v1.md)。

|新检查的边界|观察|
|---|---|
|同一份预测输入|EXACT调用一次权威澄清；PERFORMANCE直接使用授权predicate预测；两者均1最终计划、2个已记录源响应、0模型|
|声明与实际配置|两个模式预算实际传入strong/physical入口；未消费的旧截断参数、epsilon、内嵌凭据、源版本漂移在调用前拒绝|
|可信绑定|预测不能覆盖已验证身份，不能擅自改变年龄等未授权槽位；请求SHA不符即拒绝|
|按需澄清|预检不读取响应文件；执行时内容pin不符则失败，0最终计划、0源请求|
|旧真实请求回放|复用原模型提议及Neo4j/Fuseki两份原始响应，1最终计划且Cara/e4一致；0新网络、0新tokens|
|失败回放|完整失败可准确复现且保留原query失败；失败原因改变不算成功复现；未返回/不完整调用拒绝认证回放|

14项不同的新增案例、2项受影响案例分别通过。首次12项新案例+2项受影响检查为
14 passed/1.45s；随后围绕失败回放增加2项检查。保留了两次实际失败：测试夹具误用
ExecutionReport位置参数，以及自动导出pin多出bytes字段导致读回被拒绝。前者改为
明确命名字段，后者保持严格path/hash校验并允许核对实际bytes；最终目标案例
1 passed/0.50s。修复后CLI发布与v2成功回放也通过。未把重复运行计作更多案例。

失败回放不仅比较“仍然失败”，还核对工具值、节点、状态和错误原因。源响应按精确
artifact匹配一次，允许独立请求启动顺序变化。回放成功表示复现成功，不把原始失败
改成答案成功。先前v1文件与两次失败目录全部保留，无自动重试或live fallback。

本次部署冻结估计器沿用旧训练权重（父模型`33badbbe…`），只离线读取新tiny graph的
14条逻辑JSON记录，更新源版本与统计量；部署模型`6436a41a…`。无fit、新采样或按
当前query结果调参。60.5B是逻辑记录宽度，不是HTTP大小，迁移没有校准保证。

可复现入口：

```bash
PYTHONPATH=src python -m xgap.experiments.practical_records --help
```

实际CLI命令、返回码、源文件哈希、旧门及失败记录保存在
[v2验证索引](/Users/anthonyche/xgap-data/practical-profile-20260914-v2/verification.json)。
[发布配置](/Users/anthonyche/xgap-data/practical-profile-20260914-v2/published-profile.json) SHA
`1c77b3c9dc495f8e83b88bc73df3ca2efa2aa35b15fbd6271cd946743d356f93`；
[回放receipt](/Users/anthonyche/xgap-data/practical-profile-20260914-v2/replay/receipt.json)。
[仓库证据索引](../../experiments/artifacts/practical_profile_20260914.json)。

当前配置只服务开发：源地址为未部署localhost:1，不能称为新的真实服务结果或论文
campaign release；之前的一次live整体门仍按其旧版本报告。可信模板与caller权威
输入仍是边界，不证明任意NL解释、EXACT一般准确率或PERFORMANCE速度优势。

下一项是明确实际成本和冻结估计排序的验收口径，再从已保存的小图轨迹诊断信息/
规划/执行的主导成本，决定最小必要新测量。保留性能负结果，不为新候选调分数；
不提前进行大量消融。9月15日02:00收尾总结并暂停，10:00继续；总体Goal未完成。
