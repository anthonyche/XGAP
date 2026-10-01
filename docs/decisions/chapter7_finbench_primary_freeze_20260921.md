# FinBench primary comparison: pre-outcome freeze

2026-09-21。基于已封存的三结构 pilot 和用户批准的双取样框，冻结第一份正式主比较。
范围是 FinBench-derived、原生 Neo4j+Fuseki、NL→materialized rows，对应 E1/E2/E7/E8。
这不替代同事实 RDF 外部比较，也不表示三数据集/E1–E20 已完成。

## 样本、重复和分析

- 两个[取样框](chapter7_sampling_strata_20260921.md)各 24 题，三个结构各 8 题。
  仅 formal fold。每个框内独立锚点不重复，跨框可能重叠但保留同一 family ID。
  另排除此前 offline constructor gate 的源中首个词典序 ID：账户
  `100205091708996946`、公司 `100`，因为该 gate 未采用 pilot 抽样器。
  该排除只依据已经开发暴露的身份，不依据其答案。
- 每题每方法一次；Exact 与 Performance 共 96 个预定单元，ε=1/2，零自动重试。
  只有一轮测量，不声称已估计同题重复方差。每个结构/框的先运行方法各占一半，
  题目顺序用固定随机流交错两个框，全部顺序在参考答案计算前封存。
- 正式样本量参考 pilot 的配对 NL 差异标准差 2.832 s。预定有意义的耗时差异为
  10%（以 pilot Exact 19.002 s 计，为 1.900 s）；常用正态工作近似
  `ceil(((1.96+0.84)*2.832/1.900)^2)=18` 对。为三个结构等额及平衡方法顺序取 24 对/框。
  这是粗略预算依据，不保证实际检验功效；active 框的方差和模型长尾可能不同。
- 所有正式请求进入质量分母。失败/非回答 F1=0；两边均空 EM/F1=1，仅一边空为0；
  保留已有顺序、重复和 decimal3-half-up 规则，不按结果改变评分。
- 两个框分别报告；耗时仅用两方法共同回答的固定集合并附集合大小及全请求失败。
  保存逐题配对、template、frame、family ID，后续区间按 family 聚类。
  不因不显著或不利结果增加样本，不把两个框混为一个优势结论。

## 固定系统和资源

复用已接入的 SF0.1 原始事实、Neo4j+Fuseki 源映射、冻结 estimator、Qwen 服务及
compact-v2 接口。public scope 同样提供两模式；私有 intent 仅经计量模拟用户披露。
保持 scope、候选数 16、四个坐标及权重2/2/1/1、denominator=6；没有初始私有答案线索。

- 源/请求/参考/config/代码 commit/model profile 全部哈希封存。
- 10 s planning 上限、16 个可选改进动作，90 s/method、64 backend calls、20 s/call。
- worker 1 GiB、source 2 GiB 观测边界；64 MiB/response、256 MiB/phase。
- 整批最多 96 次模型请求/最终计划、2 小时 wall（含断点间隔）、2 GiB retained package；
  保留 6 GiB 空闲磁盘。任何预算截止如实截断，不能换目录重置同一 study 预算。
- 沿用72小时整体新增实验材料8 GiB上限。本批额度只占其中2 GiB，其他正式批次单独冻结
  但不能补充整体额度。不得将未运行的其余扫描误写为已启动或已完成。
- 在测量批次内不安装依赖、不编译、不准备其他数据。服务端缓存不清空；使用新 serving
  session、每次新 worker、固定交错顺序，明确这是共享暖化条件，不能声称强制 cold-cache。
- 离线装载/索引/参考单列；保持原始调用和压缩结果，0 current-query trial plans。

ARUQULA 原版依赖、Redis 与官方 lookup 接口已通过各自环境门；真实图 metadata 和
模型/FedUP 串接仍待完成。它的原生 Neo4j 部署为 UNSUPPORTED，RDF 接入为 SETUP_ERROR
直至完整接口验收，不能画成零正确率或声称 XGAP 已击败它。
