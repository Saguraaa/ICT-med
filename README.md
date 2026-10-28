# MedRoute 医路智分

面向 AgentArts 托管运行时的医学辅助分诊**研究原型**。根据 MDAgents 的复杂度路由、角色招募、讨论与报告汇总思路独立重构，增加信息追问、风险优先、证据核查与人工交接出口。不是原论文数值结果的复现，也没有进行临床验证。

## 已实现

- 按风险、信息完整度和复杂度决策：追问、单专家、小组、多团队或人工升级。
- 从全科、呼吸、心血管、消化角色池动态选择参与者（有限角色池，不是任意生成专科）。
- 小组讨论有轮次上限和主持者复核；所有参与者读取上一轮全体意见。
- 高复杂度依次执行初评团队、专科讨论、最终审核团队；最终汇总读取全部报告。
- 本地 JSONL 词项检索，以及可对接 MedRAG 等服务的 HTTP 检索适配器。
- 引用 ID 完整性检查与额外模型支持性复核，异常、预算耗尽或依据不足时返回人工处理。
- 真实 AgentArts SDK 入口 `app.py`；无需安装依赖的本地 HTTP 入口 `local_app.py`。
- 独立会话状态、调用次数、token 使用量、运行时间与精简执行轨迹。
- 三种协作策略供实验：adaptive、single、fixed_multi；各策略保留风险与信息检查。

## 先运行离线演示（无密钥、无付费模型调用）

建议 Python 3.12。以下命令在 PowerShell 中执行：

```powershell
cd E:\impfile\imp\ICT\med
$env:MODEL_BACKEND = 'demo'
python evaluation.py
python -m unittest discover -s tests -v
python local_app.py
```

在另一个 PowerShell 中：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/ping
$body = @{message = 'demo [demo:moderate]'} | ConvertTo-Json
$r = Invoke-RestMethod http://127.0.0.1:8080/invocations -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
$r | ConvertTo-Json -Depth 20
```

演示使用明确的合成标记，不会根据真实症状推断病情。`[demo:moderate]` 走小组，`[demo:high]` 走多团队，`[demo:clarify]` 追问，`[demo:redflag]` 在模型调用前升级，`[demo:urgent]` 在模拟评估后升级。所有输出带演示标识。演示中的“引用复核通过”只验证软件链路，不验证医学内容。

如需验证追问，将上次响应的完整 `case_state` 随下次 `message` 传回。可用 `[demo:complete]` 完成合成追问。

## 接入真实模型

1. 复制 `.env.example` 为 `.env`，填写自己开通的模型名称和密钥。
2. 将 `MODEL_BACKEND` 改为 `openai`。它表示 OpenAI 兼容的 HTTP 协议，不限定模型厂商。
3. `MODEL_URL` 是服务根地址，例如华为 MaaS 的 `https://api.modelarts-maas.com/openai/v1`。程序会追加 `/chat/completions`。
4. 清除前面为演示设置的环境覆盖：PowerShell 执行 `Remove-Item Env:MODEL_BACKEND -ErrorAction SilentlyContinue`，或者显式设为 `openai`。已有环境变量优先于 `.env`。
5. 运行 `python local_app.py`，提交真实模型测试输入。没有配置模型时明确返回 `model_not_configured`，不会自动退回演示。

本原型要求模型按提示返回 JSON；不支持结构化输出或输出格式不合规时会转人工。没有隐式重试，每一次实际尝试计入调用预算。

DeepSeek 官方地址默认开启 JSON Output（`MODEL_JSON_MODE=auto`）。其他兼容服务若支持该参数，可设置 true；不支持时设置 false。JSON Output 只约束 JSON 语法，不保证业务字段和医学判断正确；程序仍逐字段校验。invalid_triage 时查看 diagnostics.validation_errors 定位缺失或不合规字段，不需要在日志中暴露病例和原始模型输出。

**真实分诊输出默认关闭。** 随附的知识和风险规则均为合成测试数据，真实模式不使用这些数据。要研究真实分诊流程，需自行接入有来源且经审核的知识与规则；`ENABLE_TRIAGE_OUTPUT=true` 与规则审核标志只是工程开关，不等于临床有效性认证。默认设置也可以完成模型与服务接入测试，但不会返回自动分诊结论。详见 [检索接入](docs/RETRIEVAL.md)。

## 项目结构

| 文件 | 职责 |
|---|---|
| `app.py` | AgentArts 官方 SDK 服务入口 |
| `local_app.py` | 本地标准库 HTTP 服务；默认仅监听本机 |
| `medroute.py` | 请求校验、路由与协作过程 |
| `agents.py`、`prompts.py` | 模型协议、角色提示词、预算与演示后端 |
| `retrieval.py` | 外部资料检索及来源元数据 |
| `safety.py` | 规则、结果校验和引用完整性检查 |
| `service.py` | 统一异常处理，不泄漏上游错误详情 |
| `evaluation.py` | 批量运行数据集和比较协作策略 |
| `data/` | 合成示例；需替换成正式资源 |
| `tests/` | 路由、消息传递、引用、预算、HTTP 和 SDK 测试 |
| `Dockerfile` | AgentArts 服务镜像，入口为 `app.py` |

部署步骤见 **[AgentArts 部署手册](docs/DEPLOY_AGENTARTS.md)**。接口见 [API 说明](docs/API.md)，方法归属见 [来源与差异](docs/PROVENANCE.md)。

逐步执行与通过条件见 **[部署执行与验收计划](docs/DEPLOYMENT_PLAN.md)**，用于记录每一步通过、失败或未执行。

## 评测

```powershell
$env:MODEL_BACKEND = 'demo'
python evaluation.py --strategy adaptive --output work/adaptive.json
python evaluation.py --strategy single --output work/single.json
python evaluation.py --strategy fixed_multi --output work/fixed_multi.json
```

演示测试的 expected_route 是自适应策略标签，固定策略得到不同路由是预期结果。演示集仅检查软件分支，不计算医疗准确率。真实评测需要独立病例、经过复核的紧急程度/路径/证据标注，并报告漏分诊、过度分诊、引用支持率、成本和延迟。程序输出调用数和 token 用量，未硬编码费用或价格。

## 接口行为和边界

- 每次仅接收一条新消息；会话通过客户端携带的 `case_state.user_messages` 延续。服务不保存在进程级变量中的病例历史，也不承诺服务器端持久化。客户端必须限制用户只访问自己的病例状态。
- 客户端传入的既往风险结论、引用或专家意见不作为可信状态；每次按全部用户文本重新检查。没有自动接管人工的外部系统，交接字段明确为 `not_connected`。
- 生产数据中不要使用 `demo=true`；`reviewed=true` 必须反映真实审核，不能为通过程序而修改。文档来源、适用人群、更新时间需由资料维护方负责。
- 当前风险规则仅做字面匹配；否定、历史和假设表达可能误触发。不要将该机制单独用于真实风险判断。模型评估补充语义判断，但同样未经临床验证。
- 同一个底层模型承担多个角色会产生相关错误；模型支持性复核不是独立临床审核，也不保证消除幻觉。
- 截止时间在阶段之间检查，并限制每个网络操作的超时；不是可以强制终止任意上游计算的硬实时期限。上游报错不会输出原始响应体或密钥。
- `reports`、`case_state` 和 `retrieved_evidence` 包含敏感业务内容，面向终端用户只展示 `response` 与适用的来源；开发追踪信息限授权人员访问。代码默认不记录患者文本，但 AgentArts 自身的调用日志仍需在控制台按部署要求配置。
- `MODEL_BACKEND=demo` 只能演示流程，不能用于患者服务。第一版不包含真实医疗数据、真实人工接诊连接、医学图像输入和论文全量基准结果。
