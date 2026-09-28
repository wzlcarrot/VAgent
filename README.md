<div align="center">

# VAgent

**ViewHub 的 AI 智能助手**

提供视频问答、个性化视频推荐、个人数据查询与平台使用帮助。

</div>

---

## 功能

- 视频内容智能问答
- 个性化 / 冷启动视频推荐（基于 ViewHub 真实行为画像：tags / 分区 / 点赞 / 收藏）
- 用户点赞、收藏、播放历史数据查询
- 平台使用帮助与客服对话
- 多轮对话与跨会话记忆
- 赞踩反馈影响下次推荐排序
- 意图路由：关键词 + 语义 + LLM 三阶段，**单标签**（一条请求只进入一个工作流）；决策实时可见（SSE meta 事件）
- 显式 CoT：路由分歧时先分步推理再裁决，推理过程写入 Run Trace
- 多模态：DeepSeek `deepseek-flash` 支持图文混合输入（`deepseek-vl` provider）

## 快速开始

Docker 已收进 ViewHub 仓。本仓只保留应用代码；一键启动：

```bash
# 在 ViewHub 目录（.env 里 VAGENT_ROOT 指向本仓）
cd /path/to/ViewHub
docker compose up -d --build
```

- 前端：http://localhost:4091
- API 文档：http://localhost:9090/docs

本地开发（不起本仓 compose）：`ai-end` 用 uvicorn，`ai-frontend` 用 Vite，数据库连 ViewHub 的 Postgres。

## 测试

```bash
# 后端（覆盖率门槛 72%，无 omit）
cd ai-end && python -m pytest tests/ -q --cov=app

# 路由黄金集（离线，分方法命中表）
cd ai-end && python scripts/golden_set.py --no-llm

# 双路召回对比（BM25-only / vector-only / 融合）
cd ai-end && python scripts/ablate_recall.py --top-k 5

# Run Trace 离线回放
cd ai-end && python scripts/replay_trace.py --session <session_id> --run <run_id>

# Behavior Golden Set（路由 + 指代 + Tool Policy）
cd ai-end && python scripts/behavior_golden_set.py

# 全链路 Workflow Golden（mock DB/LLM）
cd ai-end && python scripts/workflow_golden_set.py

# 同义口语「当前视频」问答（改写命中 / 硬负例拒答）
cd ai-end && python scripts/synonym_video_qa_eval.py

# 前端（statements/lines 75%）
cd ai-frontend && npx vitest run --coverage
```

## Agentic Video RAG

针对**当前正在看的这个视频**做问答：不是一次性 RAG，而是轻量 Agent 闭环（只搜本视频内容，避免跨视频串答）：

1. **Query rewrite**：规则口语扩展 + 可选 LLM 关键词改写  
2. **检索漏斗**：`recall_budget` → `rerank_candidate_limit` → `default_top_k`（启动校验单调收窄）  
3. **批级 EvidenceGate**：最高精排分低于阈值则整批不进 LLM（借鉴 Ragent）  
4. **当前视频混合召回**：`pgvector` + ParadeDB BM25，并过滤掉其他视频的片段；证据不足则多轮补搜  
5. **Corrective**：启发式 + 可选 LLM judge 校验证据支撑，不支撑则补搜一轮或拒答  
6. **Bounded ReAct**：检索节点最多 3 次 `search_video_chunks` tool call（`video_qa_react`）  
7. **Citations**：结构化引用（含可跳转时间点）经 SSE 回传并**持久化到 chat_history**，刷新会话仍可展示  

检索-only 调试：`GET /ai/rag/eval?question=...&video_id=...`（需登录，不调用答案生成 LLM）。

检索预热：`python3 ai-end/scripts/demo_warmup.py --base http://127.0.0.1:4091 --token <jwt>`

SSE 回归（离线 CI）：`python3 ai-end/scripts/sse_regression.py --offline`  
端到端证据校验：`python3 ai-end/scripts/demo_evidence.py --base ... --video-id ... --admin-key ...`  
Live 五五开验证：`python3 ai-end/scripts/sse_live_suite.py --base ... --video-id ...`  
15 轮 live：`python3 ai-end/scripts/viewhub_live_regression.py --full ...`  

**Java 索引回调 SLA**：见 [`docs/java-index-callback.md`](docs/java-index-callback.md)  
**运维质量看板**：Admin →「本周质量」或 `GET /ai/admin/business-quality`

Playwright E2E：`cd ai-frontend && npm run test:e2e`（mock SSE）；`E2E_LIVE=1 npm run test:e2e`（真实登录）

离线评测：

| 脚本 | 用途 |
|------|------|
| `workflow_golden_set.py` | 全链路 workflow 输出（6/6） |
| `behavior_golden_set.py` | 路由 + 指代 + Tool Policy（22/22） |
| `synonym_video_qa_eval.py` | 口语 hit / 硬负例拒答（9/9） |

演示：`export VAGENT_DEMO_MODE=1` 启用 LLM replay（**仅 mock LLM**；检索改写 / EvidenceGate / grounding 与生产一致）。当前视频问答支持 **Bounded ReAct**（默认最多 3 次 `search_video_chunks`）。

## License

MIT
