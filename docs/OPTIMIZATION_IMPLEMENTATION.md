# 优化实施记录

2026-11-10：首期工程实现，尚未完成正式医学效果验收。现有默认路径保持 baseline，未修改云端部署和本地真实密钥。

## 模块

- A：`collaboration.py` 管理相关问题、最新报告、相关上下文和保守角色选择。`COLLAB_POLICY=context` 仅裁剪通信，`selective` 同时选择后续轮角色。选择为空时回退全部角色，并记录 fallback。
- B：`evidence_loop.py` 实现最多一轮、两次补证，新增证据动态进入引用集合；相同 ID 不同内容拒绝、重复查询跳过、最多8篇，容量不足转人工。低复杂度存在不确定性时也能进入主持审核及补证。患者事实缺失只能追问。
- C：`integration.py` 核查逐 claim 的报告/证据引用；`INTEGRATION_POLICY=evidence_first` 启用结构化采纳记录。未实现微调，不支持 finetuned 配置。
- `benchmark.py` 运行 S/F/B0/A-context/A/B/C/AB/AC/BC/ABC 交错配对对照，保存源码、数据、知识库与规则哈希、逐次结果和汇总。
- `metrics.py` 按 case_id/repeat 配对，病例聚类 bootstrap 动作正确率差值，保留负提升；零基线相对提升为 NA，缺失 usage 为 null。
- `reporting.py` 生成 CSV、JSON 与 Markdown。模型自报 verify 不计医学正确；demo 不计医学正确率。

启用三项（在运行智能体的环境中配置，而非仅聊天客户端）：

```dotenv
COLLAB_POLICY=selective
EVIDENCE_POLICY=gap_driven
INTEGRATION_POLICY=evidence_first
MAX_EXTRA_RETRIEVAL_ROUNDS=1
MAX_FOLLOWUP_QUERIES=2
```

## 运行与结果

```powershell
python -m unittest discover -s tests -v
python benchmark.py --output work/benchmarks/my-demo --repeats 3
```

输出目录必须不存在，避免覆盖旧实验。默认无付费调用；显式 `--live --input <审核病例.jsonl>` 才读取真实模型配置。
病例字段为 `id,message,case_state`；正式动作标签使用 `reviewed:true,allowed_actions:[...]`，标签仅评测器读取，不进入模型输入。
completed 使用 care_level；其他使用 route。审核动作标签不足以自动评估所有关键建议内容，仍需独立人工审核。

本次 7 个演示病例 × 11 变体 × 3 次重复 = 231 次流程运行，结果在 `work/benchmarks/optimization-demo-20261110`。
演示 token 为0，不能计算节省率；医学提升率均未测。没有运行真实模型对照，不新增付费实验。

## 尚未完成的计划要求

目前评测为可运行起点，不能宣称 T0–T4 全部验收：尚缺 S3 采样基线、冻结专家意见挑战集、逐阶段 token 分摊、
费用/P95/高风险召回/独立证据支持与纠错指标，以及这些指标的聚类置信区间和阈值自动判定。
运行清单记录当前源码哈希；实施前未单独留存完整未提交源码快照，不能把 Git HEAD 冒充完整原始基线。
默认关闭优化的 B0 是同基础设施行为基线。

需要负责人提供：审核病例（开发/测试隔离）、可用审核知识库和规则、独立评分标签/审核流程、正式实验预算。
具备这些后才可生成具有医学意义的提升率与最终验收结论。SFT 与并行化仍属后续条件阶段。
