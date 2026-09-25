# 27 题批量诊断交接：通用优化与一天内收尾

工程提交：`4b80d3d128e57752dd5ef8dd845bc2d1eea9eb0a`。
计划：[一天内收尾](../decisions/one_day_readiness_20260925.md)。
用户已上传、校验、部署并提交 **3874119**，随后主动取消排队中的作业。用户贴回
`CANCELLED`、`RunTime=00:00:00`、`AllocTRES=(null)`；27 题未开始执行。
旧 stage 拒绝重复部署是预期行为。用户已执行基于 sacct 历史记录的恢复命令，
三个文件 SHA 均通过，替代作业 **3874144 已 COMPLETED/0:0 于 compt304**，
作业总耗时 43:09；用户日志报告 27/27 覆盖、24 correct、3 source_timeout、remaining=[]。
原始归档已完成 SHA、答案、计划、请求分类及六段关闭核验，不重复提交。见[结果及边界](ch6_census_terminal_3874144.md)。
尚未达到全量正式实验启动条件。
当前日志：`/home/hxc859/xgap-ch6-artifacts/rdf-census27-4b80d3d-v2/rdf-census27-3874144.out`。
预期归档：`/home/hxc859/xgap-rdf-census27-3874144.tar.gz`。
调度更新：3874144 已原地解除 compt311 限制，`ReqNodeList=(null)`；后续 squeue
证实已在 compt304 启动。作业号、脚本、代码、题目和资源预算不变。
以下上传步骤保留为历史交接记录，不要重复执行。

## 已完成

- 源请求/整题超时可配置；历史默认保持 60/120 秒。
- 新 census 按冻结顺序覆盖未执行题。资源超限被记录，不自动重试；只有关闭证明
  完整才接续下一段。答案错误、未知异常、回执不全或资源无法关闭会停止。
- 28 项定点测试通过；覆盖预算、失败分类、无重复、观察器及深度/五方法合同。
- 剩余 RDF 原索引 5–31 的 27 题全部通过零调用规划检查，选中计划已冻结；零
  直接全边读取节点、2–6 个绑定读取节点。这不是答案正确性或性能实测结果。
- 代码、输入、旧结果、选中计划、运行参数已固定；与 ac97d16 相比生产 planner、
  compiler、scheduler 和 estimator 未改变，不重新训练或根据当前题试跑择优。

## 唯一待交接包

本地文件：`/Users/anthonyche/Downloads/xgapcensus27-4b80d3d-v2.zip`，38,398 字节。

SHA-256：`cc532b2a6b67a161577f7c9c718d0b18ccf028b3f8144c4d65fbed3e78c69c3a`。

通过 OnDemand 上传到 `/home/hxc859` 后，只执行下面一行一次。不要使用 v1 或之前
的 next8 包。服务器控制此前持续不可靠，因此本次保留人工文件交接；未重复提交。

```bash
python3 -c 'from pathlib import Path; import hashlib,zipfile; p=Path("/home/hxc859/xgapcensus27-4b80d3d-v2.zip"); assert hashlib.sha256(p.read_bytes()).hexdigest()=="cc532b2a6b67a161577f7c9c718d0b18ccf028b3f8144c4d65fbed3e78c69c3a"; exec(compile(zipfile.ZipFile(str(p)).read("stage.py"),"stage.py","exec"))'
```

提交脚本先检查旧归档、全部新题输入、源 runtime、源码与包校验，再唯一提交 CPU
作业。最多 27 次最终计划执行、0 LLM、0 EXPLAIN；不修改完整 MovieLens 20M，
不启动五方法正式矩阵。源请求 60 秒、整题 120 秒、方法/源 3/4 GiB 均保持原值。
每个源会话最多 8 题；源会话关闭后才切换。总诊断调度预算 8 小时，Slurm 作业
上限 8 小时 15 分钟；这不是预计运行时长，实际计时及未执行题均写入回执。

输出在 `/home/hxc859/xgap-ch6-artifacts/rdf-census27-4b80d3d-v2/rdf-census27-<JOBID>.out`。
归档在 `/home/hxc859/xgap-rdf-census27-<JOBID>.tar.gz`。
`census_complete=true` 仅表示指定诊断覆盖完成；必须分别查看 `all_answers_correct`、
分类计数与未执行列表，不能当成 `formal_campaign_ready=true`。

## 剩余启动条件

1. 已完成 27 题原始证据验收（24 correct、3 source_timeout）；保留超时，不逐题改写。
2. 完成版本影响核对及源运行配置冻结。
3. 允许声明性能超限的[可评价合同](../decisions/backend_evaluation_eligibility_20260925.md)
   已实现并通过 28 项本地检查，实际完整部署证书仍待生成。保持旧严格准入字段
   不变；错误答案及未解释异常不得借“超时可接受”放行。
4. 通过三域、实际因子输入、五方法支持合同、F6、重复数与总预算发布审计。

全量实验仍停在发布边界；本包只用于后台诊断和准备工作。

## 用户取消后的恢复

首次恢复命令因 `scontrol` 已查不到旧作业而在提交前退出，未提交新作业。新版通过
`sacct -X` 历史记录核对原作业，复用既有 checkout 和运行脚本，无需重新上传或克隆。原作业
确为取消且零运行/未分配资源、原提交记录、三个脚本/合同 SHA、原日志和输出目录
均未产生，再原子创建 `replacement-after-3874119-v1` 记录一次替代提交。原记录不删除。
13 组本地调度模拟覆盖取消、仍在排队、已运行、曾分配、已有日志/输出、历史记录
缺失/错误/重复、脚本被改、提交失败及
重复运行拒绝。替代提交不会自动绕开 CPU 排队，也不改变节点和时间/内存预算。

F6 发布检查已补上原始评分行与图状态一致性、有限非负测量值、完整源预算一致性。
TS 不可评分位置保持 null；3 项定点检查通过。现有 12 次真实成本测量未重跑，
实际正式单元绑定仍待发布材料齐备。

## 节点限定造成的排队与已执行修改

用户提供同次查询：现有 3874144 限定 compt311，预计 `2026-10-02T22:21:19`；
相同 8 CPU、24 GiB、8:15 时限、单节点 batch 的 `--test-only` 在不限定节点时，
预计 `2026-09-25T02:14:56` 可在 compt304 启动。均为服务器显示时间与调度预测，
不是实际开跑。3874173 是 test-only 编号，不是已提交作业。

脚本使用共享 `/home/hxc859` 下的冻结数据和运行时，以及 `SLURM_TMPDIR`/`/tmp`
的作业独立服务副本；没有依赖 compt311 专属文件。用户已执行官方支持的
`scontrol update JobId=3874144 ReqNodeList=`，回执确认 `ReqNodeList=(null)`。
修改前后记录保存在原 journal 的 `node-policy-update-3874144-v1`。
此操作不修改原 sbatch 文件的 SHA，也不取消、重提或重新克隆。

修改后回执仍显示旧 `StartTime`/`SchedNodeList`，尚未证明调度预测已刷新。
`SchedNodeList` 是预计节点，不应误认为已恢复硬性 `ReqNodeList`。
必须读取后续实际分配和终态；不能宣布已经开始或保证某个时间立即启动。

本批是后端可运行性诊断。新节点上的耗时需单独标明实际环境，不能与 compt311
历史记录混算速度提升。后续诊断默认不固定单个主机；正式性能比较则冻结可比较的
硬件类别和资源配置，在同一执行单元共享源服务。F6 与正式图绑定仍需核对真实环境，
不能仅因查询成功就宣称不同节点的成本测量可互换。

依据：[Slurm scontrol 的 ReqNodeList](https://slurm.schedmd.com/scontrol.html)，
允许用空值清除指定节点列表；本次已由实际回执证实修改被接受。

后续实际结果：用户 squeue 确认 **3874144 RUNNING / compt304 / 2026-09-25T01:31:38**。
节点限制解除到实际启动已闭环，尚未收到任何本批最终答案或成本结果。
