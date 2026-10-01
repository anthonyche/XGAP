# 普通请求只加载一次冻结依赖

实现`28d733f`，[生命周期与计时契约](../decisions/practical_preparation_v1.md)。
旧入口在一次请求中4次加载catalog bundle；已通过明确的请求内快照复用降至1次。
完整profile、两模式、intake、catalog/bindings、估计器与源配置仍先验证，再执行。
没有跨请求答案缓存，也没有把准备耗时从在线成本中减去。

5项新检查及2项受影响检查首次全部通过（0.94s）：完整成功回放、加载次数、计时包含、
请求开始后文件改变不影响已验证快照而下一次重新验证拒绝、错误profile/config/bundle
身份、澄清文件的延迟读取与哈希、完整失败原因回放。无数据库、模型或网络调用。

额外一次CLI同等入口的离线审计，复用已保存的一次模型观察及两份native响应；完整
outcome一致。模型历史372token仅为provenance，新调用/新token均0。
前后各一次已曝光回放总记录耗时87.411/72.776ms，只作诊断记录，不外推速度优势。
本次admission11.987ms、core58.494ms、request_total70.569ms，全部record72.776ms。
这些为嵌套范围，不能相加；receipt包括请求准备与持久化，不把catalog构建重新计费。

[旧审计](/Users/anthonyche/xgap-data/practical-preparation-audit-20260914-before/preparation_audit.json)、
[新审计](/Users/anthonyche/xgap-data/practical-preparation-audit-20260915-after/preparation_audit.json)、
[新完整receipt](/Users/anthonyche/xgap-data/practical-preparation-audit-20260915-after/receipt.json)、
[证据索引](../../experiments/artifacts/practical_preparation_20260915.json)。

下一处核心集成缺口已明确：共同实验worker仍调用旧one-shot入口，新strong模式尚未
通过这一外层计时/资源监督接口。下一步接入明确命名的strong方法和可信模板输入范围，
保留旧method IDs、所有baseline路径与既有campaign计划；只做已有响应回放的定向检查。
不自动把新方法塞进旧NL总体图，不把可信模板/额外验证信息当作无辅助开放NL能力。

检查：

```bash
PYTHONPATH=src:tests:scripts python -m pytest -q tests/test_practical_preparation.py
```

MaterialPassport: exposed development replay; no new paid evidence, fit or baseline
changes; no latency population claim. Goal仍active；02:00总结暂停、10:00恢复。
