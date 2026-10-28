# MedRoute 接口

## POST /invocations

```json
{"message":"本轮用户描述","case_state":{"user_messages":["上一轮用户描述"]}}
```

message 必填，最多 4000 字符；历史最多 11 条，总文本最多 16000 字符。超限返回 invalid_input，避免静默截掉历史风险。case_state 不包含应被信任的模型结论。

响应主要字段：

| 字段 | 含义 |
|---|---|
| status | completed / need_more_info / escalated / handoff / error |
| route | single / multi / multi_team / clarification / safety_escalation / human |
| mode | demo / openai；demo 绝不能被解释为真实推理 |
| response | 给用户的中文答复 |
| case_state | 下一轮原样携带，仅包含原始用户消息 |
| triage | 风险、复杂度、信息缺项及路由理由 |
| reports | 本次专家与团队简短报告，不是内部思维过程 |
| retrieved_evidence | 本次召回的外部原文与来源 |
| citations、claims | 通过检查后实际使用的引用与关键建议 |
| verification | 引用支持性复核；模型判断可能出错 |
| handoff | 原因、病例信息、未解决问题、transfer_status=not_connected |
| trace | 阶段、角色、检索 ID 和停止条件 |
| metrics | 模型调用次数、返回的 token 使用量和运行时间 |
| diagnostics.validation_errors | 模型评估结构不合规时的字段与预期类型，不包含原始模型值或病例原文 |

临床不足/模型失败等返回可展示的 handoff，不假装产生正确答复。输入非法是 error。local_app.py 对非法输入返回 HTTP 400，对内部异常返回 500；云端 SDK 的 HTTP 封装状态由其协议控制，调用方还需检查响应中的 status。

本地 `/ping` 不校验临床能力，只表明进程可响应。云端 `/ping` 由 AgentArts SDK 提供，不含本地自定义的 mode 字段。

## 中文编码

`app.py` 的业务响应显式设置 `Content-Type: application/json; charset=utf-8`，避免部分旧 Windows PowerShell 将 UTF-8 JSON 当作其他编码读取。更新此文件后需要构建新镜像并更新运行时版本，已有云端镜像不会自动改变。客户端仍应按 UTF-8 读取响应原始字节。给请求指定 Content-Type 的 charset 不等于替服务端设置响应编码。

local_app.py 的 LOCAL_API_TOKEN 只保护本地 invocations，默认 localhost；云端使用 AgentArts 网关鉴权。不要把本地服务器当作公网生产服务。
