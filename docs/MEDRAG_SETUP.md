# MedRAG 公开医学语料接入

本实现使用 MedRAG 官方 Textbooks 片段＋SQLite FTS5 BM25（英文 Porter 分词），不是完整上游 MedRAG/MedCPT 复现。
生成与专家协作仍使用现有模型，无需GPU和额外Python依赖。
来源：[语料卡](https://huggingface.co/datasets/MedRAG/textbooks)、[代码](https://github.com/gzxiong/MedRAG)。
公开下载不等于原始教材版权开放，使用及再分发需核对原始资料条款；仓库不提交教材或索引。

## 下载与建库

在含 medrag_store.py 的目录执行：

```powershell
python medrag_store.py --download First_Aid_Step2 --output data/medrag.sqlite
```

约2.5MB，仅为18本教材中的一个子集。输出片段数、原文件SHA256以及索引旁的manifest。
正式实验应加 `--revision <官方数据集commit>` 冻结版本，默认main可能变化；脚本拒绝覆盖已有索引。
可自行下载官方 chunk/*.jsonl 后执行：

```powershell
python medrag_store.py --input D:/datasets/First_Aid_Step2.jsonl --output data/medrag.sqlite
```

多个输入文件可扩展教材范围。源更新时间未知时明确标记unknown，不把导入时间当出版日期。

## 配置运行智能体的环境

```dotenv
RETRIEVAL_BACKEND=medrag_sqlite
MEDRAG_INDEX_PATH=data/medrag.sqlite
RETRIEVAL_URL=
EVIDENCE_SCOPE=research
ENABLE_TRIAGE_OUTPUT=false
```

保留现有真实模型配置。中文病例会调用模型生成英文关键词，计入总调用与token预算。
research允许未审核真实资料参与研究分析，reviewed仍为false；最终发布门控仍转人工，
即使ENABLE_TRIAGE_OUTPUT=true也不会在research模式发布自动分诊结论。
正式审核知识继续使用 docs/RETRIEVAL.md 中的JSONL或HTTP接口，不批量伪造reviewed=true。

## 验证

```powershell
python -c "from medrag_store import search_index; import json; print(json.dumps(search_index('data/medrag.sqlite','cough fever',2),ensure_ascii=False,indent=2))"
```

无需模型密钥即可验证英文检索、真实段落、来源与hash。完整链路运行python local_app.py提交合成病例，
查看retrieved_evidence、reports、trace及handoff；最终人工提示是研究模式预期结果。

## AgentArts 与队友客户端

chat_server.py调用云端智能体，只修改本机.env不会使云端接入RAG。
现有Dockerfile复制根目录脚本和data/，从含索引目录重建镜像、推送SWR、更新AgentArts镜像和上述环境变量后生效。
无需另建常驻ECS检索服务。队友只运行聊天客户端时，无需下载知识库。
data/*.sqlite和manifest被Git忽略；下载语料放work/。不要把完整教材加入Git。
