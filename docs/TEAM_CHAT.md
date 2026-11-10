# 团队聊天页面

架构：成员浏览器 → chat_server.py → 已部署的 AgentArts 运行时。无需更新智能体镜像。
本页面用于小团队合成病例联调，不包含账号管理、聊天数据库或真实人工接诊。

## 本机启动

在 med 目录的 `.env` 中追加（不要提交真实值）：

```dotenv
AGENTARTS_RUNTIME_URL=https://defaultgw-my2weytcmi.cn-southwest-2.huaweicloud-agentarts.com/runtimes/runtime-tei5co2j/invocations?endpoint=Latest
AGENTARTS_RUNTIME_KEY=填写运行时入站APIKey，不是DeepSeek密钥
CHAT_ACCESS_CODE=
```

运行 `python chat_server.py`，浏览器打开 http://localhost:8090 即可测试。
`CHAT_ACCESS_CODE` 留空时不需要口令，页面自动隐藏口令框，适合可信内网。
如需限制访问，将它设置为至少 12 位的随机口令，重启后生效。
这台机器无需安装模型依赖，Python 标准库即可，但必须能访问运行时 HTTPS 地址。

验收：留空口令时可直接使用；设置口令后错误口令拒绝调用；追问后补充信息能延续前一轮；
“新建对话”会重置上下文。测试详情可查看 request_id、路由及原始响应。
浏览器不应收到运行时密钥，页面刷新会清空当前会话，不存入 localStorage。

## 同一内网的团队

运行 `python chat_server.py --host 0.0.0.0 --port 8090`。
使用 `ipconfig` 找到电脑内网 IPv4，成员访问 `http://该IP:8090`。
Windows 防火墙仅向需要的内网地址开放 TCP 8090，电脑和程序必须保持运行。
仅在可信内网使用该 HTTP 方式；共享口令并非独立成员账号。

## 异地访问 / ECS

1. 将 `chat_server.py`、`config.py`、`web/index.html` 上传到单独目录。
2. 在该目录创建 `.env`，填入上述三个变量；限制文件仅服务账号可读。
3. 用进程管理工具保持 `python chat_server.py --host 127.0.0.1 --port 8090` 运行。
4. 为域名配置 DNS 和 HTTPS，用 Nginx/Caddy 将请求反代到 `127.0.0.1:8090`。
   反代等待时间设为至少 150 秒；安全组仅放行实际所需端口，8090 不对公网开放。
5. 团队访问 HTTPS 域名，项目负责人私下提供测试口令。

公网验收：HTTPS 正常，错误口令被拒绝，连续两轮对话成功，重启后服务可恢复，
网页源代码和浏览器网络请求均不含 AgentArts 入站密钥。
本服务限制同时转发最多 4 个请求，超出返回繁忙；没有完整的暴力破解防护或用户限额，
公开推广前需增加网关限流、成员账号与调用配额。先用于受控小团队测试。

## 已知限制

网页使用独立网关，不能将此 URL 当作 AgentArts 新的页面路径；AgentArts API 地址仍保持原样。
运行时缺少审核知识资料时，网页仍会显示对应人工处理提示，网页不会绕过证据门控。
本地验证使用模拟运行时，不代表已验证云上密钥、网络或实际模型输出。
