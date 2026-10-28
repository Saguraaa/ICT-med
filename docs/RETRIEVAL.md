# 医学知识与检索服务接入

## 本地 JSONL

每行一个独立片段，UTF-8，至少包含：

```json
{"id":"stable-document-and-chunk-id","title":"资料标题","content":"经过审核的原文片段","source":"真实来源URL或内部文档标识","updated_at":"2026-10-28","population":"适用人群和条件","reviewed":false,"demo":false}
```

`reviewed` 表示真实审核状态，需由资料维护人员确认后更改。真实模式只使用 reviewed=true 且 demo!=true 的片段。ID 必须唯一，更新时需保留可追溯版本。本地检索只是中文双字/英文词项重合与 IDF 的轻量基线，不是向量检索、BM25 或原论文 MedRAG。

单条原文最多 12000 字符。来源标识只是元数据；系统不会自动联网确认 URL 是否有效，避免把 ID 存在误称为医学事实正确。建议在资料入库阶段完成来源与版本审核。

## 外部 HTTP 合同

将 RETRIEVAL_URL 配为完整服务 URL。后端会发送 POST：

```json
{"query":"病例摘要与用户消息","top_k":4}
```

可选鉴权：`Authorization: Bearer <RETRIEVAL_API_KEY>`。接收：

```json
{"documents":[{"id":"source-001-v1-chunk2","title":"标题","content":"检索到的真实原文","source":"来源地址或文档标识","updated_at":"2026-10-28","population":"适用条件","reviewed":true,"demo":false}]}
```

外部服务应提前排序，程序最多取 top_k。该合同适用于自建 MedRAG 适配服务，也可用来桥接平台检索 API。检索供应方受部署管理员信任，不能把前端用户上传的任意 evidence 当作已审核知识。

MedRAG 官方工具返回 answer、snippets、scores；需在独立服务中将 snippets 转换为上面的 documents，并补充真实来源、更新日期和审核状态。**本项目没有下载 MedRAG 的大规模语料和索引，也没有把演示检索冒充为 MedRAG。**

如果需要让 AgentArts 知识库直接提供检索，依据控制台实际 API 或已部署工作流建立适配服务，转换 output_list 字段。不要猜测未核对的私有 API 地址。原生[知识检索节点说明](https://support.huaweicloud.com/lowcode-agentarts/agentarts_05_0086.html)列出了 query 输入与 output_list 输出。

## 引用复核

1. 检索获取有元数据的原文。
2. 专家引用片段 ID。
3. 最终答复逐条列出 claims 与证据 ID。
4. 程序检查 ID 真实存在于本次检索结果。
5. 额外模型检查整段答复和逐条建议的支持关系与适用性。
6. 任一步不通过，返回人工处理；默认真实输出发布开关还必须通过。

第 4 步是确定性检查，第 5 步是存在误判可能的模型判断。两者不构成临床正确性保证。

## 风险规则文件

`data/red_flags.json` 格式包含版本、全局 reviewed 标志和规则列表。每条规则需包含 id、patterns、source、reviewed、demo。随附规则仅匹配 `[demo:redflag]`，不是医学红旗清单。

实际维护应由医疗专业人员定义适用范围、升级路径、来源和例外；当前执行器仅做不区分大小写的字面匹配，无法可靠处理否定、既往和假设。这些场景应纳入人工复核和测试，不能通过添加几条关键词就宣称完成临床分诊安全设计。
