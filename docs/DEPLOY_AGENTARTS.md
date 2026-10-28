# 部署 MedRoute 到 AgentArts

本项目采用“一个 Python 服务包含路由和多个专家角色，整体托管”的方式。无需把每个专家部署为独立容器。部署不会自动生成画布上的专家节点。

## 1. 你需要准备

- 已开通的 AgentArts 和依赖云服务授权。
- 与目标运行时同区域的 SWR 镜像仓库组织、部署权限和调用凭证。
- Python 3.12；官方当前要求 ARM64 镜像，建议按官方文档在 Ubuntu ARM64 构建。
- 真实模式需要已经开通的模型服务及可访问的服务地址。先用 demo 验证云端链路也可。
- 本机尚未完成云端部署；没有在代码中预填任何个人密钥、账号、网关或仓库。

以下是截至 2026-10-28 核对的官方入口：

- [托管智能体到运行时](https://support.huaweicloud.com/qs-agentarts/agentarts_04_0004.html)
- [控制台部署](https://support.huaweicloud.com/bestpractice-agentarts/agentarts_06_0066.html)
- [Runtime SDK](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_041.html)
- [IAM 调用](https://support.huaweicloud.com/api-agentarts/agentarts_07_0033.html)
- [API Key 调用](https://support.huaweicloud.com/api-agentarts/agentarts_07_0035.html)

用户提供的 `bestpractice-agentarts/agentarts_06_0067.html` 本次读取超时；实际接口依据上面可读取的官方文档，并在本机使用真实 SDK 验证。具体已验证项目见 `VALIDATION.md`。

## 2. 在本地验证官方 SDK 入口

将整个 med 文件夹复制到构建环境，进入该目录。在 Linux ARM64 上：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export MODEL_BACKEND=demo
python app.py
```

另开终端：

```bash
curl http://127.0.0.1:8080/ping
curl -X POST http://127.0.0.1:8080/invocations \
  -H 'Content-Type: application/json' \
  -d '{"message":"demo [demo:moderate]"}'
```

应返回 `route=multi`、`mode=demo` 和调用统计。`app.py` 使用真实 `AgentArtsRuntimeApp` 的 `@app.entrypoint`，没有以自制类伪装平台 SDK。

Windows 本地开发可运行 `python local_app.py`（无第三方依赖），或装好 SDK 后 `python app.py`；云端镜像入口始终是 `app.py`。

## 3A. 推荐：手动镜像 + 控制台

以下在 ARM64 构建机 med 目录执行。将示例组织名、区域和仓库替换为控制台实际信息。

```bash
docker build -t medroute:0.1 .
docker image inspect medroute:0.1 --format '{{.Architecture}}'
# 必须确认输出 arm64；不要将本机 Windows/x86 镜像直接用于当前 ARM64 运行时。
docker run --rm -p 8080:8080 -e MODEL_BACKEND=demo medroute:0.1
```

再次验证 ping 和 invocations。随后按 SWR 控制台生成的指令登录，不要将登录凭证写入源码或 README。

```bash
# 仅为地址示例：以控制台显示的同区域仓库为准
docker tag medroute:0.1 swr.cn-southwest-2.myhuaweicloud.com/YOUR_ORG/medroute:0.1
docker push swr.cn-southwest-2.myhuaweicloud.com/YOUR_ORG/medroute:0.1
```

在 AgentArts 控制台进入“智能体运行时”，选择“托管智能体”，配置：

| 配置 | 本项目建议 |
|---|---|
| 名称 | `medroute` |
| 镜像 | 刚推送的同区域 SWR 镜像 |
| 协议与端口 | HTTP，8080 |
| 启动命令 | 留空，Dockerfile 已设置 `python app.py` |
| 路由 | 按官方快速开始使用前缀匹配；请求采用默认 invocations 入口 |
| 入站认证 | IAM；若需从工作流方便调用，可按账号条件配置 API Key，并遵循对应调用文档 |
| 出网 | 能够访问模型和检索服务；公网模型需要相应出网能力 |
| 环境变量 | 初次只设 `MODEL_BACKEND=demo`，确认链路后切换真实配置 |
| 文件上传下载 | 本项目纯文本接口无需开启 |

创建并等待状态正常，再用详情页提供的地址、认证方式和会话头调用。不自行猜测网关域名。

如果 Docker/SWR 提示 OCI 格式不兼容，按官方部署文档检查构建器和镜像格式配置；不要盲目更换成未知镜像源。

## 3B. 可选：SDK CLI 构建部署

在 ARM64 构建机 med 目录完成模型环境与华为部署凭证配置后：

```bash
agentarts configure --entrypoint app:app
agentarts launch
agentarts invoke --agent medroute '{"message":"demo [demo:high]"}'
```

`configure` 按提示填写运行时名称、可用区域、依赖文件和 SWR 组织。官方快速开始当前给出 `cn-southwest-2`，实际以你的账号开通情况及最新控制台为准。SDK 负责镜像构建、推送与部署；请确认它使用的构建环境和 Dockerfile 满足 ARM64 要求，并在运行时环境中配置 `MODEL_BACKEND=demo`。没有 Docker 的电脑不能仅安装 Python SDK 就完成容器构建。

部署凭证使用 `HUAWEICLOUD_SDK_AK` 和 `HUAWEICLOUD_SDK_SK`（或控制台支持的方式），模型凭证使用 `MODEL_API_KEY`；二者用途不同。不要在聊天、命令示例或 Git 中提交真实值。

## 4. 切换真实模型与证据

在运行时环境变量中配置（值需自己填写）：

```text
MODEL_BACKEND=openai
MODEL_NAME=你实际开通的模型名称
MODEL_URL=https://api.modelarts-maas.com/openai/v1
MODEL_API_KEY=模型服务密钥
ENABLE_TRIAGE_OUTPUT=false
```

不需要为了使用华为 MaaS 重写路由；只要模型支持 chat/completions 兼容协议和 JSON 指令即可。实际返回格式不合规会转人工，而非继续猜测。

上传或接入经过审核的医学资料，格式见 `RETRIEVAL.md`。默认示例数据真实模式会被过滤，因此“服务已经连上模型但返回 no_reviewed_evidence”是明确的资料缺失提示。没有通用医学知识库被偷偷内置。

真实规则与资料版本是模型请求之外的配置；更新镜像内 JSONL/规则需要重建镜像并发布版本，外部检索库可独立维护。保留旧镜像标签以便回滚。

## 5. 在 AgentArts 工作流中调用（可选）

1. 创建对话型工作流，开始节点收集本轮 message。
2. 添加 HTTP 请求节点或已发布的 API 插件，调用托管运行时的 invocations 地址。
3. 根据已选择的入站认证配置请求头；网关 API Key 与模型 API Key 不同。
4. 将 message 和上一轮返回的 case_state 映射进 JSON 请求体。
5. 保存响应 case_state 到当前用户会话变量，下一轮传回。新会话置空，禁止跨用户共享。
6. 根据 status 显示 response。need_more_info 继续问答；handoff/escalated 显示交接提示；只有 completed 展示完成答复和来源。
7. 核心路由在 Python 内执行，画布无需再独立判断单/多 Agent。只有需要重做业务边界时才拆分路由职责。

平台支持[HTTP 节点和判断节点](https://support.huaweicloud.com/lowcode-agentarts/agentarts_05_0041.html)及[工作流插件](https://support.huaweicloud.com/lowcode-agentarts/agentarts_05_0132.html)。本项目未提供“可直接导入的平台工作流包”，因为这还依赖你实际的网关、插件与会话变量配置。

## 6. 部署后验收

- demo 模式分别提交 data/demo_cases.jsonl 的七类输入，检查 route、trace、reports 和 metrics。
- 多团队最终决策读取初评、各专家和最终审核报告；轮次及调用次数不超过预算。
- 不同用户独立携带自己的 case_state；新会话不继承其他病例。
- 真实模式缺密钥、检索服务报错、空检索、伪造证据 ID 或模型格式错误时，不输出自动分诊结论。
- 人工交接为 not_connected，除非另行接入并确认真实接诊服务；不能在界面显示“已接通医生”。
- 配置网关访问权限、调用限额和日志访问范围。不要将开发报告和完整病例状态直接公开展示。
