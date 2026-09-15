# XGAP Current Status

2026-09-15。可信有界模板下的新strong核心与共同真实入口已通，论文配置/总体评价
尚未完成。用户已授权恢复；10:04核实后从干净提交1b7f2af继续，恢复时没有本任务活动native服务。[Goal与工作时段](goal.md)优先于历史记录。

## 当前实现与证据

|环节|已有证据|边界|
|---|---|---|
|Strong策略与信息工具|P-S1 22新+3受影响；P-S2 14+3；真实catalog与双后端tiny|有限声明结果的strongness，不保证任意服务永不失败|
|Live模型同请求链|1模型372token、1计划2源请求、正确1行，在线812ms|可信模板的一槽提议，不是开放NL结构验证；[报告](report/practical_model_e2e_20260914.md)|
|逐跳策略与成本诊断|真实逐跳正确；同会话第二序列协调器145ms、首跳169ms、逐跳174ms|未证明逐跳提速；不改估计分数；[报告](report/practical_cost_diagnostic_20260914.md)|
|重复源读取共享|11新+1受影响；真实调用14→11、响应18606→16399B，4行gold保持|完整同源同artifact范围；[报告](report/shared_native_reads_20260914.md)|
|必要源过滤|14新+2受影响；真实源行64→61、响应16399→15820B，另1次Cypher类型门|保留最终typed过滤；[报告](report/source_row_prefilters_20260914.md)|
|请求准备|5新+2受影响；bundle加载4→1，完整回放一致|准备成本仍在线计量；[报告](report/practical_preparation_20260915.md)|
|合作式规划预算|6新+1受影响；到期保留基础/已改善完整计划|原子步骤可越时；[报告](report/cooperative_planning_budget_20260915.md)|
|新strong共同worker|6新+1受影响；随后1输入检查+真实EXACT请求：4行gold、11源调用、外层1711ms|owned服务全部关闭；[报告](report/practical_worker_native_20260915.md)|
|大trace/小outcome|4新+1受影响；>16MiB中间记录、<4KiB摘要正确交付|全trace仍保留/占内存；[报告](report/practical_outcome_20260915.md)|
|大源记录回放|5新+1受影响；>16MiB合法JSON捕获完整回放，源容量界限512MiB|非流式/规模实证；[报告](report/practical_capture_size_20260915.md)|
|独立study接线|6新检查；现补1真实group/双模式，各4行gold、1计划/11源调用|总22源调用，0模型，owned服务关闭；[新报告](report/resolved_strong_inputs_20260915.md)|
|完整可信查询与两表示输入|7新+3受影响检查通过；native/RDF各120题与24/48/48原划分，726生成pin校验|在线schema路由计费；新物理开发preset100/2000ms；[报告](report/resolved_strong_inputs_20260915.md)。非部分绑定或总体评价|
|部分绑定共同前端/外部组合|固定信息顺序、同模式权限、一次global SPARQL及v2调度；17新检查最终通过；真实六cell各执行一次|XGAP/FedX各模式成功返回，权限差异一致；FedUP两cell原生extend不支持；[报告](report/fixed_information_frontend_20260915.md)。36源请求、0模型/重试，全部owned服务已关|
|部分绑定FinBench输入候选|两表示各120题、24/48/48原划分，968 pin；10新+1受影响检查最终通过；12次开发离线规划均strong|仅关系标签共享槽；0模型/源执行；发现EXACT模型提议后仍全部需权威步骤；[报告](report/partial_strong_inputs_20260915.md)|
|EXACT证据推进剪枝|7新+1受影响case最终通过；六个原EXACT输入仍strong且终端集合相同，状态24→4、动作7→1|两种进程内权威答案均正确/零模型/一最终计划；规划时间未一致降低，PERFORMANCE及固定外部顺序保持；[报告](report/exact_information_pruning_20260915.md)|

所有计数按对应里程碑原始记录，不把重复的受影响检查累加为独立实验样本。新记录
接口/profile有可调用实现；它们不是占位文档。当前测试只覆盖声明边界。

## 尚未实现与尚未验证

- 完整语义与部分绑定FinBench候选输入已发布；论文模式profile/release尚未发布。
  EXACT冗余模型前缀已剪枝；下一步冻结实际信息成本/排序依据及最终模式配置。
  外部同权限组合前端已实现且真实小图已运行；FedUP当前生成形式的原生不支持保留，
  不能作为优化器速度优势。正式评价仍未启动。
- 任意NL结构的权威验证、用户待定义的d/epsilon保证尚未实现；新模式明确限定可信结构。
- 实际两模式质量/速度优势、估计排序泛化、regret与scalability尚未证明。
- 旧FinBench真实结果存在，含错误/失败、空与非空答案，按原版本/曝光保存；不能换名
  为新strong模式分数。旧NL44个结果、native固定20题、RDF固定5组不合并成同质主结果。

[系统边界与18图草案](research_contract_audit_20260915.md)解释剩余接线、输入权限与结论。
更多历史数据见[旧状态逐字快照](status_history_20260915.md)，其旧“下一步”不再生效。
