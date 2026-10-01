# 大执行记录不再阻断小答案的共同worker交付

实现`ef119a6`，[交付边界](../decisions/practical_outcome_v1.md)。审查正式评价接线时发现：
新worker通过16MiB通用读取器重读完整core trace，可能把已成功的查询误报为交付失败。
现在producer同时封存完整trace与小型outcome；worker只读取答案、语义状态与实际计量
摘要，并保留完整trace pin。旧one-shot已经采用类似边界，本次补到新strong入口。

4项新定向检查及1项受影响检查通过：第一批3+1共0.87s，后补未知usage/null执行值
1项0.21s。所有检查首次通过；旧成功检查不重复。受控回放把一个中间节点行载荷扩大
到超过16MiB，完整执行记录仍保留，最终Cara/e4答案不变，worker从
小于4KiB的outcome成功交付。该载荷仅测试记录大小，不代表新大图查询或规模实验。

此外，outcome引用另一个trace会拒绝；新记录未封存outcome时不退回读取大trace；
旧的小记录仍兼容；缺失usage/执行时间保持unknown；原本失败的请求回放后仍为失败。
不重读源响应、不修答案、不更改任何算法/估计器/数据/基线，0新模型/源调用/fit。

完整轨迹生成与内存成本仍然存在，写摘要也计入在线成本。16MiB输入校验没有放宽，
本轮没有实现无界最终答案流式接口。真实共同native门的前一版本结果保持原样，
本次交付改动只用本地回放验证，不重跑已成功真实请求。

检查：`PYTHONPATH=src:tests:scripts /tmp/xgap-directed-tests.qU2YfW/venv/bin/python
-m pytest -q tests/test_practical_outcome.py`中的前三例及共同worker原失败回放；
随后仅检查`test_missing_usage_and_null_execution_value_remain_unknown`。第一工具会话
17824已确认exit0，第二命令直接exit0。[证据索引](../../experiments/artifacts/practical_outcome_20260915.json)。

下一步继续新strong研究/评价契约审计。将“功能已有但证据未覆盖”与“实际未实现”
逐项区分；尤其明确可信模板、外部方法可比信息、两模式当前配置和未定义discrepancy。
02:00收尾、10:00恢复。

MaterialPassport: controlled record-size replay and failure-boundary evidence;
zero new network/large-data execution, no statistical scalability claim.
