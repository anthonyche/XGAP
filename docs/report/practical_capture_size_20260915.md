# 实际源响应的回放使用源记录容量界限

实现`66f1783`，[边界契约](../decisions/practical_capture_size_v1.md)。新practical回放在
admission阶段误用16MiB配置文件读取器，而已有BackendReplay消费端支持有界512MiB
源记录。现在两者对齐；配置、manifest和outcome仍保持16MiB上限，大小/hash在读取
及消费时都核验。完整源响应不被剪裁，也不会因回放失败而切换到真实调用。

5项新检查+1项受影响失败回放首次通过（0.73s，工具会话25500确认exit0）。在原源
记录后增加合法JSON空白使文件超过16MiB，其值、查询artifact和期待结果完全不变，
严格完整回放成功；无效/过大/布尔size在文件打开前拒绝，缺省size仍核验hash与截断。
这是文件容量边界，不是模拟图规模或新大图实验；零新网络/模型/fit/baseline。

大JSON回放仍需要与文件大小成比例的内存，不宣称流式或无界能力。原BackendReplay
与baseline没有修改；只去掉了不一致的前置读取界限。不重跑已成功native门。
[证据索引](../../experiments/artifacts/practical_capture_size_20260915.json)。

MaterialPassport: bounded capture-file replay; no graph-scale result or new paid calls.
