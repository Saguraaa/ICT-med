# MedRoute 部署执行与验收计划

规划日期：2026-10-28。状态：待执行；本文件不是云端部署完成记录。

采用一条主路线：**Python 核心 → ARM64 镜像 → SWR → AgentArts 托管运行时 → 可选对话工作流**。
先验收演示服务，再接真实模型和资料。演示上线、真实模型接通、医疗能力验收是不同里程碑。

## 第 1 步：确认账号、区域和构建环境

操作：开通 AgentArts，完成依赖服务授权；确认目标区域可用，创建同区域 SWR 组织；准备 Ubuntu ARM64 构建环境、Docker 和 Python 3.12。准备部署账号权限。此步不需要真实模型密钥。

验收：
- 控制台能进入智能体运行时与 SWR，具备创建/推送权限。
- `uname -m` 输出 `aarch64`；`docker version` 同时有客户端与服务端响应。
- `python3 --version` 显示计划使用的 3.12；确认构建源能下载基础镜像和依赖。
- 记录区域、组织、镜像名、运行时名称，不记录密钥。官方快速开始当前以贵阳一为例，实际区域必须在账号可用范围内。

失败排查：未授权服务、IAM 权限、区域未开通、Docker 未启动或构建机架构错误。

## 第 2 步：在目标构建机复跑代码

操作：上传 med 源码，排除 `.env`、work、虚拟环境和缓存；按 DEPLOY_AGENTARTS.md 安装 requirements.txt，设置 `MODEL_BACKEND=demo`，运行单元测试及 evaluation.py。

验收：
- `python -m unittest discover -s tests -v`：当前版本 34 项通过、0 失败、0 跳过。SDK 测试跳过不能当作完整通过。
- `python evaluation.py`：7 个合成案例、7 个路由匹配、26 次模拟模型调用。
- 保存测试结果、Python/SDK 版本与源码版本标识。这些是功能标准，不是医学准确率标准。

失败排查：Python 版本、依赖安装、工作目录、环境变量覆盖和源码遗漏。

## 第 3 步：构建并验证容器

操作：`docker build -t medroute:0.1 .`，随后 `docker run --rm -p 8080:8080 -e MODEL_BACKEND=demo medroute:0.1`。

验收：
- `docker image inspect medroute:0.1 --format '{{.Architecture}}'` 输出 `arm64`。
- 容器持续运行，GET /ping 返回 200。
- POST /invocations 提交 `{"message":"demo [demo:moderate]"}`，返回 mode=demo、status=completed、route=multi。
- 镜像不包含 `.env` 和 work/sdk-deps，构建时未传入密钥，启动不需要宿主机源码目录。

失败排查：架构、依赖、8080 端口、SDK 入口、相对资料路径。只有这个步骤通过，才推送镜像。

## 第 4 步：推送 SWR 并确认可重取

操作：按 SWR 控制台提供的登录指令登录，给镜像添加真实仓库地址并推送。命令见部署手册，不在文档填入真实登录密码。

验收：
- SWR 中看到正确组织、仓库与 0.1 标签；记录 digest。
- 镜像与目标 AgentArts 区域一致；用另一干净 Docker 环境拉取该标签成功，检查架构仍为 arm64。
- 所拉取镜像的 digest 与推送记录一致。

失败排查：仓库地址、推送授权、区域、镜像格式及平台拉取委托。不要通过修改源码排查仓库认证问题。

## 第 5 步：创建演示运行时

操作：选择 SWR 镜像，在 AgentArts 托管运行时设置 HTTP、8080、文档建议的前缀匹配及入站鉴权。Dockerfile 已定义启动命令。先设置 MODEL_BACKEND=demo、ENABLE_TRIAGE_OUTPUT=false，不填真实模型密钥。

验收：
- 控制台运行时状态正常，没有持续启动或健康检查失败。
- 从详情页取得真实调用地址，按选定的 IAM/API Key 方式调用 POST invocations，返回 mode=demo、status=completed。
- 正确凭证允许调用；仅替换为错误凭证后请求被网关拒绝，并确认未进入业务执行。SDK 本地测试不能代替这一步。
- 记录部署版本、镜像 digest、区域、端口及环境配置名称，不记录凭证。

失败排查：启动日志、镜像拉取、监听地址、网关路径、路由配置、鉴权类型。此时 demo 不需要模型网络，先排除平台链路问题。

## 第 6 步：验收云端全部软件路径

逐条调用云端接口；不能只检查 HTTP 200。

| 输入 | 预期 status / route | 额外条件 |
|---|---|---|
| `demo 普通流程` | completed / single | 1 份专家报告，模型模拟调用 4 次 |
| `demo [demo:moderate]` | completed / multi | 3 份专家报告，调用 7 次 |
| `demo [demo:high]` | completed / multi_team | 5 份报告，调用 9 次 |
| `demo [demo:clarify]` | need_more_info / clarification | 返回追问和 case_state |
| `[demo:complete]`，带上条 case_state | completed / single | 保留两轮用户消息 |
| `demo [demo:redflag]` | escalated / safety_escalation | 模型调用 0 次 |
| `demo [demo:urgent]` | escalated / safety_escalation | 不生成专家报告 |

另做：
- 用户 A 的历史不传给 B，B 返回的 case_state 只含 B 的输入；平台会话和前端变量不能跨用户共享。
- 临时将 MAX_MODEL_CALLS=1，提交普通 demo，必须返回 handoff 且 reason=model_call_limit，不生成完成建议；验收后恢复 16。
- 每个 demo 输出含演示标识；人工交接 transfer_status=not_connected。
- 保存完整合成请求与响应记录。以上检查全部符合预期才算“云端演示服务部署完成”。

失败排查：环境变量是否更新、镜像版本是否正确、旧会话状态混用、预算参数没有恢复。

## 第 7 步：接上平台对话入口（需要画布时执行）

操作：创建对话型工作流，通过 HTTP 节点或 API 插件调用运行时。把本轮输入映射为 message，把响应 case_state 保存到当前用户会话变量并传入下一轮。展示 response，按 status 处理追问或升级。核心单/多 Agent 路由仍在 Python 内完成。

验收：
- 在平台聊天界面完成“追问 → 补充 → 完成”三步，不手动编辑请求体。
- 新会话不继承旧病例，切换测试用户不读到其他用户历史。
- 插件使用正确的网关凭证，而不是模型密钥；凭证不出现在聊天答复。
- handoff/escalated 不被界面包装成已完成诊断或已接通医生。
- 如果不需要平台聊天界面，保留 API 接入；此步骤明确记为“不在本轮范围”，不能写成已验收。

## 第 8 步：接真实模型，保持封闭测试

操作：在独立测试版本配置 MODEL_BACKEND=openai、MODEL_NAME、MODEL_URL、MODEL_API_KEY，保留 ENABLE_TRIAGE_OUTPUT=false。只提交合成描述，不用 demo 标记评价真实模型。

验收：
- 返回 mode=openai，并且 triage 是经过结构校验的真实模型结果；供应商侧能看到对应成功调用。
- 不出现 model_not_configured、upstream_http_401/403 或 upstream_unavailable_or_invalid_json。
- 资料未接入时，明确返回 no_reviewed_evidence；需要追问时返回 need_more_info；这些可以是正常业务结果。
- 准备 10 条固定的非紧急合成输入做连接/格式冒烟测试，10/10 没有鉴权、网络或格式解析错误。这个数量和通过目标是本项目工程验收建议，不是医学标准。
- 模型日志、计费侧和本地统计能相互解释；未提供 usage 的服务不能将 0 token 宣称为零成本。

失败排查：模型实际名称、URL 是否重复追加 /chat/completions、模型服务出网、密钥、JSON 格式遵循度。不要通过打开分诊发布开关解决连接问题。

## 第 9 步：接入知识与审核规则

操作：按 RETRIEVAL.md 准备有原文、来源、版本、适用条件和真实审核记录的资料；选择本地资料或外部检索服务。配置经专业人员审定的规则，保留原型发布开关关闭，先检验资料链路。

验收：
- 准备 10 个预先标注“应命中的证据片段”的检索问题；关键已知片段在 top_k 内命中 10/10，且人工确认适用性。这里只是小范围入库验收，不代表泛化检索能力。
- 非演示片段有唯一 ID、原文、source、updated_at 和可信审核记录；演示/未审核片段不进入真实结果。
- 专家和最终报告中出现的证据 ID 均属于本次检索；涉及的原文可实际查看。
- 检索失败或无结果时走 handoff，不用模型自身记忆补成有证据的答复。
- 专业人员复核规则的当前/既往、否定/肯定、假设等输入；记录字面匹配误触发，未解决则不得把规则库视为实际临床安全保障。
- 真实规则和资料尚未准备时，阶段状态写“未验收”，不能以修改 reviewed 布尔值代替专业审核。

## 第 10 步：决定是否开放真实分诊输出

这一步区别于“部署成功”。在独立测试版本上完成小范围、预先标注的病例评测与专业审核后，才考虑启用 ENABLE_TRIAGE_OUTPUT。

验收：
- 固定支持人群、服务范围和明确的升级动作，测试集与开发集分离。
- 与专业人员事先约定漏分诊、过度分诊、路径合理性和证据支持率的数值门槛；记录样本量、置信区间与失败案例。没有约定不能事后以任意分数宣布通过。
- 对预设必须升级的哨兵病例逐条检查，任何漏升级均须调查并阻止该版本发布；有限测试全通过也不代表对所有真实情况零漏判。
- 在同模型、同知识条件下比较单专家、固定小组与自适应方案，记录收益、成本和延迟。
- 如界面声称已转人工，必须连接真实接诊系统并验证请求提交、接收确认和失败回退；否则保持 not_connected 提示。
- 演练一次回滚到已验收镜像版本，配置、资料版本和调用链保持可追溯。

未通过时，继续作为内部研究/演示服务使用，不将技术上线记录写成临床能力验收。

## 每步记录模板

| 步骤 | 日期/执行者 | 版本或 digest | 验收证据位置 | 通过/失败/未执行 | 失败原因与复测结果 |
|---|---|---|---|---|---|
| 1–10 | 待填写 | 待填写 | 待填写（不放密钥） | 未执行 | 待填写 |

官方依据：[托管运行时](https://support.huaweicloud.com/qs-agentarts/agentarts_04_0004.html)、[API Key 调用](https://support.huaweicloud.com/api-agentarts/agentarts_07_0035.html)、[工作流组件](https://support.huaweicloud.com/lowcode-agentarts/agentarts_05_0041.html)。完整操作命令见 DEPLOY_AGENTARTS.md。
