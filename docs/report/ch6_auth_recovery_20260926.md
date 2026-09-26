# D1 pilot 认证恢复交接

3885715 的首个 GR 请求在约 0.55 秒收到 HTTP 401 Unauthorized；后端请求和最终
计划执行均为 0，未知 token 用量保持未知。本机及 Pioneer 登录节点的新隐藏输入
检查均返回 200、模型 `qwen3.8-27b`、输入 15 / 输出 2 token。历史拒绝原因不能
进一步归因为误输或服务变更；不能用此失败评价算法质量。

实现提交 `c40254728151972252974d63eb4befb311068b3a` 增加安全错误摘要透传和一次
启动认证探针。23 项定向代码检查通过；9 项包完整性及模拟生命周期检查通过，包括
旧作业仍运行、关闭证据缺失、非认证失败、包篡改、重复提交及认证失败前置阻断。
这些检查不冒充新计算节点上的真实运行。

包：`/Users/anthonyche/Downloads/xgappilotD1-auth-c402547-v2.zip`，22,865 字节。
SHA-256：`bd6ff3381cbe2963455e785aeada000b858531399cdfbd895444b9943decb140`。
基于服务器已有精确 `22dd334` checkout，保留旧目录；无需 GitHub 在线。

将包上传至 `/home/hxc859`，仅执行一次：

```bash
python3 -c 'from pathlib import Path; import hashlib,zipfile; p=Path("/home/hxc859/xgappilotD1-auth-c402547-v2.zip"); assert hashlib.sha256(p.read_bytes()).hexdigest()=="bd6ff3381cbe2963455e785aeada000b858531399cdfbd895444b9943decb140"; exec(compile(zipfile.ZipFile(str(p)).read("stage.py"),"stage.py","exec"))'
```

在隐藏提示中粘贴刚通过认证的密钥。stage 不继承环境中的旧密钥；一次性文件为
0600，计算节点读取后删除，不进入包或 Slurm 环境导出。计算节点用同一内存密钥
做一次最多 8 输出 token 的探针，20 秒、无重试/重定向；成功并取得完整 usage 才
装载数据库。探针单列在基础设施成本；旧轮未知消耗仍单列，不声称整体零额外成本。

原 56 题、256 个方法请求、原顺序与 4 小时实验预算不变。恢复轮重发唯一先前被
401 拒绝的请求并执行其余 255 项；没有成功查询被重复。旧失败和原用量保持原样。
不改 baseline 提示/解码/质量，不扩大到三域全量。

新 journal：`/home/hxc859/xgap-ch6-artifacts/pilot-D1-auth-c402547-v1`。
新输出：`/home/hxc859/xgap-ch6-artifacts/pilot-D1-auth-one-repeat-c402547-v1`。
包 v2 只是交接包修订，服务器目录 v1 是首次恢复尝试。运行日志为 journal 下
`pilot-<job_id>.out`。结束后摘要归档会包含小型 core/interpretation 诊断；较大原始
响应仍保留在服务器，省略项明确计量。

交接更新：用户终端已确认精确 `c402547`、1,558 项服务器审计通过、隐藏输入密钥，
输出 `SUBMISSION 3885860`。旧状态“尚未提交”已由此更新；运行节点、计算节点的
认证探针、实际完成请求和用量仍待读取。不重提、不改在途配置。只读查询为：

```bash
sacct -j 3885860 --format=JobID,State,ExitCode,Elapsed,NodeList -P; tail -n 4 /home/hxc859/xgap-ch6-artifacts/pilot-D1-auth-c402547-v1/pilot-3885860.out
```

真实证据记录、包及验证报告位于
`/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/`。
