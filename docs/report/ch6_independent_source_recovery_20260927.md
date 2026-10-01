# 48 题运行：独立源包恢复

2026-09-27。用户执行 `xgap-small48-fixed-f40dfa9-v1.zip` 时，Git 报
`ignoring alternate object stores, nesting too deep`，随后 fetch 的薄包存在
11 个 unresolved deltas。旧部署连续使用 `git clone --shared`，导致新 checkout
读取基础对象时经过过深的 alternates 链。故障位于 prepare、隐藏密钥输入、sbatch
之前；本次没有实验查询、模型调用或新作业。

## 修复范围

实验代码仍精确固定在 `f40dfa9024f1473a90e6f340fb787f90ca204c46`。
新构建器 `scripts/build_ch6_small48_independent_handoff.py` 从原校验通过的包
生成恢复包，使用不含 prerequisite 的完整 Git bundle。在空仓中 init/fetch/checkout，
核对版本、干净工作树、对象连通性及无 alternates，之后才发布输入并提交。

恢复前校验旧 staging 的精确文件集合及各文件 hash、旧 checkout 仅有 `.git`、
旧输出不存在。任何准备、凭据、提交等额外记录都会拒绝恢复。新 staging、checkout、
output 均独立；旧失败目录和旧研究结果保留。未来服务器代码交付不得继续叠加共享
克隆；独立源对象的可读性必须作为部署检查，不能只在已有本地对象库中验证增量包。

原 selection/probe policy/scalability spec 逐字节不变，预算不变。prepare/driver/
sbatch 仅改变这次部署的三个路径，不修改 provider、算法、源快照或方法预算。
48题、216个适用请求、D1→D3→D2、8 CPU/24 GiB、无 GPU，授权范围不变。

## 验证与交接

本地 21 项检查通过：Python 3.6 语法、三个输入逐字节对照、预算对照、四执行文件仅
路径变化、bundle 无 prerequisites、空仓精确还原及 `git fsck --full --no-reflogs`、
模拟唯一提交、重复提交拒绝、旧准备/凭据/提交文件出现即拒绝、旧失败目录不变。
模拟提交编号 9000001 只是测试夹具，不是 Slurm 作业。真实外部调用和作业提交为零。

验证记录：
`/Users/anthonyche/xgap-data/outputs/xgap-independent-handoff-20260927-v1/verification.json`。

新包：`/Users/anthonyche/Downloads/xgap-small48-independent-f40dfa9-v1.zip`
（8,516,781 bytes）。SHA-256：
`017b228a8a52d119e81424d2fa7f094905b36ba0382cf51e3b765df9df207c22`。

服务器 staging：
`/home/hxc859/xgap-ch6-artifacts/small48-fixed-f40dfa9-independent-v1`。
输出：`/home/hxc859/xgap-ch6-artifacts/small48-fixed-results-f40dfa9-independent-v1`。
日志：staging 下的 `small48-<JOBID>.out`。尚待上传与服务器提交；没有新运行句柄。
本项只关闭源交付缺陷，不构成修复版 48 题已实测或全量实验完成。
