# 方法来源与实现差异

参考资料核对日期：2026-10-28。

- [MDAgents 官方仓库](https://github.com/mitmedialab/MDAgents)，主要参考 main.py 与 utils.py 的控制结构。
- [论文](https://arxiv.org/abs/2404.15155)：Yubin Kim 等，MDAgents: An Adaptive Collaboration of LLMs for Medical Decision-Making，NeurIPS 2024。
- [MedRAG 官方工具](https://github.com/gzxiong/MedRAG)。
- 华为 SDK/部署接口来源见 DEPLOY_AGENTARTS.md。

本项目独立编写代码与中文提示词，没有复制上游文件或改写其许可声明，也没有把上游未公开的功能当作已提供的代码。公开仓库所见版本的模型映射、团队报告传递与实验入口并不能直接满足本项目服务化目标。

| 设计 | 本项目处理 |
|---|---|
| 复杂度自适应协作 | 保留 low / moderate / high 三种协作层次 |
| 专家招募 | 在有限的四类角色中动态选择，最多三个；不是论文任意专家生成的严格复现 |
| 讨论与主持者 | 显式传递上一轮全体意见，达到条件早停，否则预算耗尽转人工 |
| 多团队 | 初评 → 专科小组 → 最终审核；汇总读取所有报告，非原论文同参数实验 |
| 医疗风险 | 新增独立风险/信息完整度判断与升级出口 |
| 检索 | 新增本地词项基线与 HTTP 合同，未包含原论文 MedRAG 实验的全量语料与配置 |
| 引用检查 | 新增 ID 确定性检查和模型支持性复核 |
| 应用形态 | 文本多轮分诊原型；不含原论文图像/视频问答实现 |
| 性能验证 | 软件测试与合成流程评估，不声称论文准确率或临床有效性 |

研究或展示时应同时说明上述来源与改动，不将 MedRoute 的扩展归为 MDAgents 原作贡献。
