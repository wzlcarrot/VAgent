<div align="center">

# VAgent

**Multi-Agent AI 助手：视频问答 / 视频推荐 / 用户数据查询 / 智能客服**

基于 FastAPI + LangGraph 的 Parallel Specialist + Supervisor 架构，4 路 workflow 并行执行，三阶段意图路由（关键词 → Embedding 语义 → LLM 裁决），pgvector + ParadeDB BM25 双路召回，内置节点级 Checkpoint、工具治理（Tool Governor）与 Prompt Injection 防御。

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![Vue](https://img.shields.io/badge/vue-3.4+-green.svg)
![LangGraph](https://img.shields.io/badge/langgraph-1.x-orange.svg)
![FastAPI](https://img.shields.io/badge/fastapi-0.139-009688.svg)
![PostgreSQL](https://img.shields.io/badge/postgresql-16-blue.svg)

</div>

---

## 目录

- [核心特性](#核心特性)
- [架构](#架构)
- [快速开始](#快速开始)
- [本地开发](#本地开发)
- [API 一览](#api-一览)
- [Agent Harness](#agent-harness)
- [安全设计](#安全设计)
- [测试](#测试)
- [项目结构](#项目结构)
- [License](#license)

---

## 核心特性

| 模块 | 说明 |
|------|------|
| **并行 Specialist 架构** | 4 个独立 LangGraph Workflow，Router 分发 + Supervisor 仲裁，通过 `asyncio.gather` 并行执行，总延迟 ≈ `max(workflows)` |
| **三阶段意图路由** | 关键词（1ms）→ Embedding 语义（10ms）→ LLM 裁决（1s）逐级降级，命中率高时压到毫秒级 |
| **Supervisor 仲裁** | 优先级 `video_qa > user_data > recommend > chat`，纯规则 < 1ms，零 LLM 调用 |
| **双路 RAG** | pgvector 向量召回 + ParadeDB BM25 全文召回融合，LLM Rerank 精排 |
| **多模态** | 上传图片后走编排管线，文本生成阶段切换视觉模型，编排逻辑不变 |
| **记忆系统** | 跨会话长期记忆，自动提取偏好（preference/activity/fact），按相关度召回 + 时间衰减，👍👎 反馈入库 |
| **指代消解** | 多轮对话中"第二个视频""刚才那个"等指代自动关联上次推荐/问答上下文 |
| **Agent Harness** | 节点级 Checkpoint（PG JSONB）+ Tool Governor（per-session 限流/超时/沙箱）+ Prompt Injection 防御 |
| **可观测性** | Prometheus 指标（LLM/路由/工具/workflow/checkpoint）+ 每请求 request_id 贯穿日志 |

## 架构

### 三阶段 Agent 编排管线

```
用户输入
  │
  ├── Router（意图路由）
  │    三阶段逐级降级：关键词(1ms) → Embedding 语义(10ms) → LLM(1s)
  │    确定主 workflow + 备选 chat_workflow
  │
  ├── Parallel Dispatch（并行派发）
  │    主 workflow + chat_workflow 通过 asyncio.gather 并行执行
  │    异常隔离：一个 workflow 异常不影响另一个（return_exceptions=True）
  │
  ├── Supervisor（结果仲裁）
  │    优先级 > 置信度：video_qa > user_data > recommend > chat
  │    最高优先级且有效回答 → 胜出；全部无效 → fallback
  │
  └── Tools（数据访问层）
      ├── PostgreSQL（业务数据，参数化查询）
      ├── pgvector（向量相似度搜索）
      ├── ParadeDB（BM25 全文检索）
      └── Redis（会话上下文 / 指代 / 限流计数）
```

**设计思想：** Router 只负责分发、不负责纠错——判断错误时 workflow 会因缺少参数返回空结果，Supervisor 自动降级到下一优先级。

> 关键架构决策（线程池 vs 全异步、cookie 会话、防枚举、注入防护）记录在 [`ai-end/docs/architecture-decisions.md`](ai-end/docs/architecture-decisions.md)。

### 4 个 Workflow

| Workflow | 职责 | 关键节点 |
|----------|------|---------|
| `video_qa_workflow` | 视频内容问答 | video_info → knowledge → summary → llm → supervisor |
| `recommend_workflow` | 个性化/冷启动视频推荐 | profile → search/cold_start → reason → summary |
| `user_data_workflow` | 用户数据查询（点赞/收藏/历史） | intent → query → response → supervisor |
| `chat_graph` | 平台客服 / 闲聊 | faq → guide → platform_docs → llm → supervisor |

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
git clone https://github.com/wzlcarrot/VAgent.git
cd VAgent
cp .env.example .env            # 编辑填入 DEEPSEEK_API_KEY（必填）
docker compose up -d --build
```

- 前端：http://localhost:4091
- API 文档：http://localhost:9090/docs
- Prometheus：http://localhost:9093

### 方式二：手动启动

```bash
# 后端（Python 3.11+）
cd ai-end
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8001

# 前端
cd ai-frontend
npm install
npm run dev        # http://localhost:4000
```

## API 一览

所有接口前缀为 `/ai`，除 `POST /login` 外均需 `Authorization: Bearer <token>`。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/ai/login` | 登录（bcrypt 密码校验，MD5 自动透明升级） |
| POST | `/ai/chat/stream` | 流式对话（SSE，主入口） |
| GET | `/ai/chat/sessions` | 会话列表（支持 `limit`/`offset` 分页） |
| GET | `/ai/chat/history` | 会话历史 |
| GET | `/ai/chat/search` | 会话内容搜索（LIKE 转义防注入） |
| DELETE | `/ai/chat/session/{session_id}` | 删除会话（校验 user_id） |
| GET | `/ai/chat/checkpoints` | 查询 workflow 断点 |
| POST | `/ai/chat/resume` | 从断点恢复 workflow |
| POST | `/ai/feedback` | 👍👎 反馈入库 |
| GET | `/ai/admin/stats` | 运营统计（`X-Admin-Key` 鉴权） |
| GET | `/health` / `/ready` | 存活 / 就绪探针 |

## Agent Harness

- **Checkpoint**：每个 workflow 节点执行后异步写入 PG `workflow_checkpoints`（JSONB 快照，线程池 + shutdown fallback），支持 `/ai/chat/resume` 断点恢复。
- **Tool Governor**：`invoke_with_governor` 统一入口 —— 沙箱校验（deny by default）→ Redis INCR 限流（跨 worker）→ 超时 → 写入 `run_artifacts` trace。
- **Context 三层隔离**：会话上下文（Redis List）+ 指代上下文（`session_ref:*`）+ 长期记忆（`user_memory`），TTL 与压缩（Compact）机制控制 token 成本。

## 安全设计

- **密码**：bcrypt 哈希存储；旧 MD5 数据登录成功后自动透明升级；统一错误消息防用户枚举
- **SQL**：全部参数化，LIKE 通配符转义
- **Prompt Injection**：RAG 召回内容经 `safe_prompt_escape` 转义 + system prompt 防御指令
- **鉴权**：token 存 Redis/内存双通道，后台定时清理；admin 接口 `hmac.compare_digest` 时序安全比较，fail-closed
- **输入限制**：问题长度、图片数量/总大小（base64 直传限制，与 nginx 8m 对齐）
- **异步一致性**：async 路由内的同步 DB/Redis 调用全部通过线程池隔离，不阻塞 event loop；workflow 执行带 120s 超时保护，防止卡死调用永久占用线程池
- **会话安全**：登录 token 写入 httpOnly + SameSite=Lax cookie（XSS 不可读、跨站 POST 不携带），localStorage 仅存非敏感用户信息；`Authorization: Bearer` 兼容非浏览器客户端

## 测试

```bash
# 后端
cd ai-end && python -m pytest tests/ -q

# 前端
cd ai-frontend && npx vitest run
```

## 项目结构

```
ai-end/
  app/
    agents/           # Router / Supervisor / 4 个 workflow
    conversation/     # 指代消解 + 智能追问
    harness/          # Checkpoint / Tool Governor / Session
    routers/          # auth / chat / feedback / admin
    tools/            # LLM / RAG / DB / 记忆 / 工具注册表
    utils/            # metrics / resilience / security
  tests/
ai-frontend/
  src/
    api/              # 后端 API 封装（SSE 流）
    components/       # Chat / Layout / Video 组件
    stores/           # Pinia（user / chat）
    views/            # HomeView / LoginView / HistoryView
docker-compose.yml    # 一键启动（ai-agent / ai-frontend / postgres / redis / prometheus）
```

## License

MIT
