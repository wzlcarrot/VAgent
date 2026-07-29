<div align="center">

# VAgent

**Multi-Agent AI 助手：视频问答 / 推荐 / 数据查询 / 智能客服**

基于 FastAPI + LangGraph 的 Parallel Specialist + Supervisor 架构，4 路 workflow 并行，三阶段意图路由，pgvector + ParadeDB 双路召回，含节点级 Checkpoint 与 Tool 治理 Agent Harness。

[🔗 GitHub 仓库](https://github.com/wzlcarrot/VAgent) · [🚀 快速开始](#-快速开始) · [🏗️ 架构](#️-架构) · [🤖 Agent Harness](#-agent-harness)

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![Vue](https://img.shields.io/badge/vue-3.4+-green.svg)
![LangGraph](https://img.shields.io/badge/langgraph-0.2.60+-orange.svg)
![FastAPI](https://img.shields.io/badge/fastapi-0.109-009688.svg)
![PostgreSQL](https://img.shields.io/badge/postgresql-16-blue.svg)
![ParadeDB](https://img.shields.io/badge/paradedb-BM25-purple.svg)

</div>

---

## ✨ 核心亮点

| 模块 | 亮点 |
|------|------|
| **架构** | Parallel Specialist + Supervisor：4 路 LangGraph workflow 通过 `asyncio.gather` 并行执行，总延迟 ≈ `max(workflows)`，不叠加 |
| **路由** | 三阶段降级：关键词（1ms）→ Embedding 语义（10ms）→ LLM 裁决（1s），90% 请求压在 1ms 级 |
| **仲裁** | Supervisor 优先级仲裁：`video_qa > user_data > recommend > chat`，纯规则 < 1ms，零 LLM 调用 |
| **RAG** | pgvector 向量召回 + ParadeDB BM25 全文召回双路融合，LLM Rerank 精排 |
| **可靠性** | **Agent Harness**：节点级 Checkpoint（PG JSONB）+ Tool Governor（per-session 限流超时）+ Context 三层隔离 |
| **多模态** | 上传图片后走编排管线，文本生成阶段切换视觉模型（MiniMax-M3），编排逻辑不变 |
| **记忆** | 跨 session 长期记忆 + 按相关度召回 + 时间衰减 + 👍👎 反馈入库 |
| **可观测** | Prometheus 指标 + LangGraph 中间状态全程可查 + 节点级 trace |

## 📑 目录

- [✨ 核心亮点](#-核心亮点)
- [🚀 快速开始](#-快速开始)
- [🏗️ 架构](#️-架构)
- [💡 核心功能](#-核心功能)
- [📁 项目结构](#-项目结构)
- [📝 API 示例](#-api-示例)
- [🤖 Agent Harness](#-agent-harness)
- [💭 架构设计决策](#-架构设计决策)
- [🎯 面试问答](#-面试问答)
- [🧪 测试](#-测试)
- [🚢 部署](#-部署)
- [🗺️ Roadmap](#️-roadmap)
- [👤 作者](#-作者)
- [🔒 安全性](#-安全性)
- [📄 License](#-license)

---

## 🚀 快速开始

### Docker Compose（推荐）

```bash
git clone https://github.com/wzlcarrot/VAgent.git
cd VAgent
cp ai-end/.env.example ai-end/.env          # 编辑填入 DEEPSEEK_API_KEY（必填）、MINIMAX_API_KEY（多模态用）
docker compose up -d                         # 一键启动（包含 postgres / redis / prometheus）
# 前端 http://localhost:5174
# API  http://localhost:9090
```

### 手动启动

```bash
# 后端
cd ai-end
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8001

# 前端
cd ai-frontend
npm install
npm run dev
```

## 🏗️ 架构

### 三阶段 Agent 编排管线

```
用户输入
  │
  ├── Router（意图路由）
  │   三阶段逐级降级：关键词(1ms) → 语义(10ms) → LLM(1s)
  │   确定主 workflow + 备选 chat_workflow
  │
  ├── Parallel Dispatch（并行派发）
  │   主 workflow + chat_workflow 通过 asyncio.gather 并行执行
  │   异常隔离：一个 workflow 异常不影响另一个（return_exceptions=True）
  │   每个 workflow 是独立的 LangGraph StateGraph
  │
  ├── Supervisor（结果仲裁）
  │   优先级 > 置信度：video_qa > user_data > recommend > chat
  │   最高优先级且有效回答 → 胜出；全部无效 → fallback
  │
  └── Tools（沙箱隔离）
      ├── PostgreSQL（业务数据直连）
      ├── pgvector（向量相似度搜索）
      ├── ParadeDB（BM25 全文检索）
      └── Redis（会话上下文缓存）
```

**设计思想：** 参考 Uber Cadence 和 DoorDash 的编排模式。Router 只负责分发，不负责纠错——如果判断错误，workflow 会因缺少参数返回空结果，Supervisor 自动降级到下一个优先级。

## 💡 核心功能

| 功能               | 说明                                                 |
| ---------------- | -------------------------------------------------- |
| 并行 Specialist 架构 | 4 个独立 LangGraph Workflow，Router 分发 + Supervisor 仲裁 |
| 三阶段意图路由          | 关键词 → Embedding 余弦 → LLM 裁决，逐级降级                   |
| RAG 检索           | ParadeDB BM25 + pgvector 向量搜索 + LLM Rerank         |
| 记忆系统             | 跨会话记忆，自动提取偏好，按相关度召回 + 置信度衰减                        |
| 对话反馈             | 每条回答 👍👎，数据存入记忆系统                                 |
| SSE 流式输出         | 逐字输出 + 三阶段状态指示器 + 推荐视频卡片                           |
| 多模态图片            | 上传图片后走编排管线，文本生成阶段切换视觉模型                            |
| 图片历史             | 用户上传的图片存入 chat_history，历史记录可回溯查看                   |
| 对话压缩             | Microcompact → LLM 结构化摘要 → 边界标记替换                  |
| 工具沙箱             | ToolRegistry + 按 Agent 隔离的调用权限                     |
| 对话搜索             | 支持搜索对话标题和内容                                        |
| **Agent Harness**   | 状态 Checkpoint + 断点恢复 + 工具治理 + Context 三层隔离        |
| 对话导出             | TXT / JSON 格式，单条或全部导出                              |
| 运营看板             | 聚合统计（对话数、意图分布、有用率），无用户隐私                           |

## 📁 项目结构

```
agent/
├── ai-end/                        # Python 后端（FastAPI）
│   ├── app/
│   │   ├── agents/                # Agent 核心
│   │   │   ├── router.py          # 三阶段意图路由
│   │   │   ├── supervisor.py      # 仲裁器
│   │   │   └── workflows/         # 4 个 LangGraph StateGraph
│   │   │       ├── chat_graph.py
│   │   │       ├── video_qa_workflow.py
│   │   │       ├── recommend_workflow.py
│   │   │       └── user_data_workflow.py
│   │   ├── tools/                 # 工具层
│   │   │   ├── data_tools.py      # PostgreSQL 操作
│   │   │   ├── rag_tools.py       # BM25 + pgvector 检索
│   │   │   ├── llm_tools.py       # LLM 调用（含多模态视觉）
│   │   │   ├── tool_registry.py   # 工具注册 + 沙箱隔离
│   │   │   ├── context_tools.py   # Redis 会话上下文
│   │   │   └── ranker.py          # 双路召回 + Rerank
│   │   ├── harness/               # Agent Harness（可靠性基础设施）
│   │   │   ├── checkpoint.py      # 节点级 Checkpoint + 断点恢复
│   │   │   ├── tool_governor.py   # per-session 限流 + 超时 + trace
│   │   │   └── session.py         # Session 状态管理
│   │   ├── routers/
│   │   │   ├── ai_router.py       # 编排管线入口
│   │   │   ├── chat.py            # 对话 / checkpoint / resume
│   │   │   ├── auth.py            # 鉴权
│   │   │   ├── feedback.py        # 👍👎 反馈
│   │   │   └── admin.py           # 运营看板
│   │   ├── models.py              # Pydantic 数据模型
│   │   └── config.py              # 环境变量配置
│   ├── scripts/
│   │   └── eval_agent.py          # Router 路由准确率评测
│   └── requirements.txt
├── ai-frontend/                   # Vue 3 + TypeScript 前端
│   ├── src/
│   │   ├── views/                 # 聊天 / 登录 / 历史 / 记忆 / 看板
│   │   ├── components/            # 组件
│   │   ├── api/                   # API 调用
│   │   ├── stores/                # Pinia 状态管理
│   │   └── config/                # 环境配置
│   ├── package.json
│   └── vite.config.ts
├── prometheus/                    # Prometheus 配置
├── docker-compose.yml
├── reasonix.toml                  # Python 项目配置
└── README.md
```

## 📝 API 示例

> Base URL: `http://localhost:9090`

### 1. SSE 流式对话

```bash
curl -X POST http://localhost:9090/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "user_001",
    "message": "推荐一些科技类视频",
    "video_id": null
  }' \
  --no-buffer
```

返回 SSE 流，每行 `data: {...}` 包含增量文本、状态指示器、推荐卡片等。

### 2. 查看 Checkpoint

```bash
curl "http://localhost:9090/chat/checkpoints?session_id=user_001"
```

返回该 session 所有节点的 checkpoint 步骤及状态。

### 3. 断点恢复

```bash
curl -X POST http://localhost:9090/chat/resume \
  -H "Content-Type: application/json" \
  -d '{"session_id": "user_001"}'
```

从 `last_completed_step` 续跑，不重做已完成节点。

### 4. 反馈

```bash
curl -X POST http://localhost:9090/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "user_001",
    "message_id": "msg_abc",
    "rating": 1
  }'
```

`rating: 1` = 👍，`rating: -1` = 👎。反馈数据进入长期记忆系统。

### 5. 对话历史

```bash
curl "http://localhost:9090/chat/history?session_id=user_001&limit=20"
```

### 6. 鉴权登录

```bash
curl -X POST http://localhost:9090/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "..."}'
```

完整 OpenAPI 文档：启动后访问 `http://localhost:9090/docs`。

## 🤖 Agent Harness —— 把"可靠性"做成基础设施

### 为什么需要 Harness？

校招面试官现在更关注：
- Agent 状态为什么会偏移？
- 工具调用为什么不会乱？
- 上下文为什么不会越堆越乱？
- 中间断了我怎么恢复？

我们用 **Harness** 系统化回答这些问题。**全部 4 个 workflow（chat、video_qa、recommend、user_data）均已接入 Harness。**

### 1. Checkpoint + 断点恢复（全 4 workflow 覆盖）

每个 LangGraph 节点执行后写入 PG：

```python
# 每个 workflow 的每个节点都有 _save_checkpoint() 调用
def video_info_node(state):
    result = {...}
    _save_checkpoint(sid, "video_info_node", state, result)  # 自动落库
    return result
```

**能力**：
- 节点级状态快照（JSONB，schema 灵活）
- 失败可恢复：根据 `last_completed_step` 续跑
- 幂等写入：同一 (session, workflow, step) UPSERT
- **全 4 workflow 覆盖**：chat（5 步）、video_qa（4 步）、recommend（5 步）、user_data（4 步）

**断点恢复流程**：
```
1. 查找最近一次 status=completed 的 checkpoint
2. 读取 state_snapshot（包含所有中间结果）
3. 确定下一个 step
4. 从下一个 step 开始执行，state 已经包含了之前的结果
```

**API**：
- `POST /ai/chat/resume` — 断点恢复，传入 session_id 即可
- `GET /ai/chat/checkpoints?session_id=xxx` — 查看 session 的所有 checkpoint 步骤

### 2. Tool Governor —— 工具治理

工具调用走统一入口 `invoke_with_governance()`：

```python
result = invoke_with_governance(
    session_id=sid,
    agent="chat_workflow",
    tool_name="retrieve_knowledge",
    arguments={"query": "..."},
    execute_fn=lambda: real_call(),
)
```

**治理项**：
- **限流**：每个工具每个 session 默认 10 次（`vector_search` 5 次，`recommend` 3 次）
- **超时**：每个工具有超时上限（`vector_search` 10s，`recommend` 15s）
- **Trace**：所有调用写入 `run_artifacts`（含参数、结果、耗时、错误）

### 3. Context 三层隔离

```
┌─ 短期 Context ─ Redis, TTL 2h ─ 流式缓冲
│
├─ Session 状态 ─ PG (chat_history + workflow_checkpoints) ─ 用户可见
│
└─ 长期 Memory ─ PG user_memory ─ 跨 session
```

**为什么分层**：
- 短期 context 丢了无所谓（流式 chunk）
- Session 状态是事实（用户可查可导出）
- 长期 memory 跨 session（偏好、反馈）
- **绝不混**：短期不进 checkpoint，checkpoint 不进 long-term

### 4. 模块结构

```
ai-end/app/harness/
├── __init__.py          # 公共导出
├── checkpoint.py        # Checkpoint + CheckpointManager + 装饰器
├── tool_governor.py     # ToolGovernor + 限流/超时/trace
└── session.py           # Session + SessionStore（内存）
```

### 5. 关闭 Harness（应急用）

```bash
HARNESS_ENABLED=0 uvicorn app.main:app
```

### 6. 校招能讲什么

> "我们设计了完整的 Agent Harness，覆盖全部 4 个 workflow：
> 1. 状态 Checkpoint 系统——每个节点都落库，支持断点恢复
> 2. Tool Governor——每个工具调用限流 + 超时 + 全量 trace
> 3. Context 三层隔离——短期/会话/长期分别存储，明确边界
> 4. 失败可恢复——节点失败自动记录 error，resume API 从 last_completed_step 续跑
> 5. 全栈闭环——不是只有接口，而是 4 个 workflow 全部接入，有 API 可调"

---

## 💭 架构设计决策

> 面试官真正追问的不是"你用了什么"，而是"为什么这样选"。以下记录每个关键架构决策的推理过程。

### 为什么用 Parallel Specialist 而不是单 Agent + 多工具？

单 Agent 模式（ReAct）把路由、检索、生成揉在一个循环里，问题是：
1. **延迟叠加** — 先路由再检索再生成，串行执行
2. **工具污染** — 所有工具对所有场景可见，LLM 容易选错
3. **不可观测** — 中间步骤混在一起，出问题不知道是路由错了还是检索错了

Parallel Specialist 的核心优势：
- **延迟取最慢而非叠加** — video_qa 和 chat 并行跑，总延迟 ≈ max(video_qa, chat)
- **工具天然隔离** — video_qa 只能调 `vector_search`，recommend 只能调 `recommend_videos`
- **可观测** — 每个 workflow 的中间状态独立，出问题直接定位到具体 workflow

### 为什么选 StateGraph 而不是 create_react_agent？

1. **状态可扩展** — StateGraph 可以定义任意字段（`video_info`、`candidate_videos`、`summary`），每个节点只读写自己需要的字段
2. **条件边可控** — `router_need_knowledge` 可根据中间结果动态路由，ReAct 的硬编码循环做不到
3. **可观测** — `invoke` 返回完整中间状态，便于调试和测试

### 为什么不做 Agent 互相通信？

参考 Uber Cadence 和 DoorDash，选了 **Parallel Specialist + Supervisor**。一次用户提问通常是单意图，不需要多步协作。并行延迟只取最慢的 Workflow，不叠加。如需多步推理，加一个 Orchestrator Graph 串起来即可。

### Supervisor 仲裁策略？

**优先级 > 置信度。** 决策树：有效回答 → 按优先级排序 → 最高优先级胜出 → 全部无效则 fallback。

优先级 `video_qa > user_data > recommend > chat`。`video_qa` 最高是因为平台的核心场景是视频内容问答，用户带着 video_id 进入对话时，优先回答当前视频的问题。如果当前不处于视频上下文，video_qa 会因缺少 video_id 返回空，Supervisor 自动降级到下一个优先级。

Router 判断错误时同理（如应该走推荐但走了问答），workflow 因缺参返回空，Supervisor 自动降级——这是设计上的容错机制。

### 为什么 Router 分三阶段？

关键词 1ms，语义 10ms，LLM 1s。逐级降级，低成本下达到 90%+ 准确率。

### 为什么记忆用 PG 不用 Redis？

记忆需要持久化、支持复杂查询（类型/相关度/时间衰减排序）、支持 JOIN。PG 适合持久层，Redis 只做会话缓存。

### 为什么对话压缩不做截断？

粗暴截断丢失决策信息。三重压缩（Microcompact 清理 → LLM 摘要 → 边界标记替换）在保留关键信息的同时控制 token。

### 多模态怎么集成的？

走编排管线，不是独立分支。Router 看到图片上下文后正常分发，Supervisor 仲裁后，文本生成阶段切换视觉模型。编排逻辑不变，只换底层生成方式。

### 为什么 Tool Governor 用 per-session 限流而不是全局限流？

全局限流的问题：一个用户高频调用会把所有用户的配额吃光。

per-session 限流的设计：
- 每个 session 对每个工具有独立的调用计数
- `vector_search` 每 session 5 次，`recommend_videos` 每 session 3 次
- 超限后返回空结果而非报错，Supervisor 自动降级
- **关键点**：限流是保护系统不被单个用户拖垮，不是保护单个用户不被系统拒绝

### 为什么 Context 分三层而不是两层？

两层（短期 + 长期）的问题：
- 短期 context 里混了流式 chunk（临时）和用户消息（需要持久化），边界不清
- 长期 memory 需要跨会话复用，但短期 context 的内容不一定值得进长期

三层设计的边界：
```
短期 Context（Redis, TTL 2h）
  → 流式 chunk 缓冲、当前对话的中间状态
  → 丢了无所谓，下次对话重新生成

Session 状态（PG: chat_history + workflow_checkpoints）
  → 用户可见的对话记录、workflow 执行快照
  → 事实层，不可篡改，支持导出

长期 Memory（PG: user_memory）
  → 跨 session 的偏好、反馈、行为模式
  → 向量检索 + 时间衰减，按相关度召回
```

**绝不混**：短期不进 checkpoint（因为是临时的），checkpoint 不进 long-term memory（因为是事实不是推断）。

### 为什么 Checkpoint 用 PG JSONB 而不是 Redis？

| 维度 | Redis | PG JSONB |
|------|-------|----------|
| 持久性 | 内存为主，重启可能丢 | 磁盘持久，崩溃可恢复 |
| 查询 | 只能按 key 查 | 支持 WHERE + ORDER BY |
| 恢复 | 需要额外序列化 | 直接读取 state_snapshot |
| 成本 | 内存贵 | 磁盘便宜 |

Checkpoint 的使用场景是"断点恢复"，需要：
1. 崩溃后能找回 → Redis 不够可靠
2. 按 session_id + workflow_type 查询 → PG 的 SQL 天然支持
3. state_snapshot 可能很大（含完整中间状态）→ JSONB 比 Redis string 更灵活

### 为什么 Supervisor 不用 LLM 而用规则？

LLM 仲裁的问题：
- **延迟** — 每次仲裁多一次 LLM 调用（~1s）
- **不可控** — LLM 可能选错，且错误不可预测
- **成本** — 每次对话多一次 API 调用

规则仲裁的优势：
- **确定性** — 优先级 + 置信度的组合是确定的，可测试
- **零延迟** — 纯 Python 逻辑，<1ms
- **可解释** — 每次仲裁结果都能追溯到具体规则

设计原则：**能用规则解决的，绝不用 LLM**。LLM 只用在需要"理解"的地方（意图识别、文本生成），不用在"决策"的地方（路由、仲裁）。

### 为什么 Embedding Cache 用内存 dict 而不是 Redis？

Embedding 调用是同步阻塞的（~10ms/次），缓存命中率高（同一问题重复出现）。

内存 dict 的优势：
- **零网络开销** — 直接 Python dict lookup，~1μs
- **线程安全** — threading.Lock 保护，多 worker 各自独立缓存
- **自动过期** — 24h TTL + 5000 容量上限，定期清理

为什么不用 Redis：
- Embedding 是高频调用（每次意图路由都要调），Redis 的网络开销（~1ms）反而成为瓶颈
- 多 worker 共享缓存的需求不强（各 worker 的查询模式相似，缓存命中率都高）

### 为什么 Token Store 迁移到 Redis？

Token 是跨 worker 共享的（用户从 worker A 登录，请求可能落到 worker B）。

内存 dict 的问题：worker A 存的 token，worker B 看不到 → 用户被踢出登录。

Redis 的优势：
- 天然支持多 worker 共享
- TTL 自动过期，不需要手动清理
- 降级方案：Redis 不可用时回退到内存 dict（单 worker 场景仍可用）

### 为什么 Resume 从 last_completed_step 续跑而不是从头重跑？

从头重跑的问题：
- 浪费已完成的计算（比如 video_info_node 已经成功了）
- 可能产生副作用（比如已经写入了部分结果）

从 last_completed_step 续跑的设计：
1. 查找最近一次 status=completed 的 checkpoint
2. 读取该 checkpoint 的 state_snapshot（包含所有中间结果）
3. 从下一个 step 开始执行，state 已经包含了之前的结果
4. 如果 next step 依赖的 state 不完整（比如 conditional edge 跳过了某步），从 snapshot 恢复

**关键点**：checkpoint 记录的是"节点执行完成后的完整 state"，不是"部分 state"。所以 resume 时 state 是完整的，可以直接续跑。

### 为什么三阶段 Router 的降级顺序是 关键词 → 语义 → LLM？

| 阶段 | 延迟 | 准确率 | 成本 |
|------|------|--------|------|
| 关键词 | ~1ms | ~70% | 零 |
| Embedding 语义 | ~10ms | ~90% | 低 |
| LLM 裁决 | ~1s | ~95% | 高 |

设计逻辑：
- **90% 的问题靠关键词就能分对**（"推荐视频" → recommend，"今天点赞多少" → user_data）
- 剩下 10% 走语义（"有没有好看的东西" → 语义相似度匹配 "推荐"）
- 最后 5% 走 LLM（复杂表述、歧义句）
- **期望延迟** = 0.9×1ms + 0.09×10ms + 0.01×1s ≈ 2ms

如果直接走 LLM，每次都是 1s。三阶段降级把 90% 的请求压到了 1ms 级别。

---

## 🎯 面试问答

### 为什么选 StateGraph 而不是 create_react_agent？

1. **状态可扩展** — StateGraph 可以定义任意字段（`video_info`、`candidate_videos`、`summary`），每个节点只读写自己需要的字段
2. **条件边可控** — `router_need_knowledge` 可根据中间结果动态路由，ReAct 的硬编码循环做不到
3. **可观测** — `invoke` 返回完整中间状态，便于调试和测试

### 为什么不做 Agent 互相通信？

参考 Uber Cadence 和 DoorDash，选了 **Parallel Specialist + Supervisor**。一次用户提问通常是单意图，不需要多步协作。并行延迟只取最慢的 Workflow，不叠加。如需多步推理，加一个 Orchestrator Graph 串起来即可。

### Supervisor 仲裁策略？

**优先级 > 置信度。** 决策树：有效回答 → 按优先级排序 → 最高优先级胜出 → 全部无效则 fallback。

优先级 `video_qa > user_data > recommend > chat`。`video_qa` 最高是因为平台的核心场景是视频内容问答，用户带着 video_id 进入对话时，优先回答当前视频的问题。如果当前不处于视频上下文，video_qa 会因缺少 video_id 返回空，Supervisor 自动降级到下一个优先级。

Router 判断错误时同理（如应该走推荐但走了问答），workflow 因缺参返回空，Supervisor 自动降级——这是设计上的容错机制。

### 为什么 Router 分三阶段？

关键词 1ms，语义 10ms，LLM 1s。逐级降级，低成本下达到 90%+ 准确率。

### 为什么记忆用 PG 不用 Redis？

记忆需要持久化、支持复杂查询（类型/相关度/时间衰减排序）、支持 JOIN。PG 适合持久层，Redis 只做会话缓存。

### 为什么对话压缩不做截断？

粗暴截断丢失决策信息。三重压缩（Microcompact 清理 → LLM 摘要 → 边界标记替换）在保留关键信息的同时控制 token。

### 多模态怎么集成的？

走编排管线，不是独立分支。Router 看到图片上下文后正常分发，Supervisor 仲裁后，文本生成阶段切换视觉模型。编排逻辑不变，只换底层生成方式。

---

## 🧪 测试

### Router 路由准确率评测

```bash
cd ai-end
python scripts/eval_agent.py
```

评测脚本会跑预置的测试用例（覆盖 4 类 workflow），输出路由准确率。

### 前端单测

```bash
cd ai-frontend
npm test                  # 单次跑
npm run test:watch        # 监听模式
npm run test:coverage     # 覆盖率
```

技术栈：Vitest + @vue/test-utils。

### 端到端测试（建议）

未来可加 Playwright 覆盖：
- 用户输入 → SSE 流式响应 → 推荐卡片渲染
- 上传图片 → 多模态切换视觉模型
- 中途刷新 → 断点恢复

---

## 🚢 部署

### Docker Compose（生产推荐）

```bash
docker compose -f docker-compose.yml up -d
```

服务编排：
- `ai-agent` (FastAPI) — 端口 9090 → 8001
- `ai-frontend` (Vue 3 + Nginx) — 端口 5174
- `postgres` (ParadeDB 镜像，含 pgvector)
- `redis` (会话缓存)
- `prometheus` (指标采集)

### 环境变量

必填：
- `DEEPSEEK_API_KEY` — 文本 LLM

可选：
- `MINIMAX_API_KEY` — 多模态视觉 LLM
- `MINIMAX_BASE_URL` — 多模态 API endpoint
- `VIDEO_SERVICE_URL` — 视频业务后端地址（用于 user_data workflow 查询）
- `LLM_PROVIDER` — `minimax`（默认）/ `deepseek`

详见 `ai-end/.env.example`。

### 反向代理建议

Nginx 前置 + HTTPS + 限流 + WAF。

### 监控

Prometheus 自动采集 `/metrics`，配合 Grafana 看：
- LLM 调用耗时 / 成功率
- Workflow 各节点耗时
- Checkpoint 写入速率
- 工具调用限流触发次数

---

## 🗺️ Roadmap

- [ ] **WebSocket 替代 SSE**（更稳的双向通道）
- [ ] **A/B 测试框架**（多 Router 策略对比）
- [ ] **Prompt 版本管理**（DVC 跟踪 prompt 变更与效果）
- [ ] **多租户隔离**（per-tenant 限流 + 数据隔离）
- [ ] **工作流可视化**（LangGraph Studio 集成）
- [ ] **端到端 E2E 测试**（Playwright）
- [ ] **Operator Agent**（多步推理编排，串起多个 workflow）

---

## 📖 项目是干什么的

**VAgent 是一个面向视频平台的 Multi-Agent AI 助手。** 想象你在 B 站、YouTube 上看视频，右下角有个 AI 助手能跟你聊天——这就是 VAgent 想做的事。

### 4 类核心场景

| 场景 | 例子 | 背后 workflow |
|------|------|---------------|
| 🎬 **视频问答** | "这个视频讲了什么？" "总结一下重点" | `video_qa_workflow` |
| 🎯 **个性化推荐** | "推荐一些科技类视频" "有什么好玩的" | `recommend_workflow` |
| 📊 **用户数据查询** | "我今天多少赞" "我的收藏记录" | `user_data_workflow` |
| 💬 **智能客服** | "你们平台有什么功能" "怎么上传视频" | `chat_workflow` |

每个用户输入都会**自动判断走哪条 workflow**，并由 Supervisor 仲裁结果。

### 不只是聊天，还包括

- 📷 **多模态**：用户上传图片，AI 切到视觉模型理解图片内容（比如"这张图里是什么"）
- 🧠 **长期记忆**：跨会话记住你的偏好（"我喜欢科技类视频" → 下次推荐更精准）
- 👍👎 **反馈学习**：每条回答能点赞点踩，反馈进记忆系统
- 📜 **对话历史**：所有对话持久化、可搜索、可导出（TXT/JSON）
- 🎥 **推荐视频卡片**：推荐结果不只是文字，还附带视频缩略图 + 链接

### 技术上的"不一样"

| 大部分 AI 助手的做法 | VAgent 的做法 |
|---|---|
| 一个 Agent 串行做所有事 | 4 个 workflow **并行执行**，总延迟取最慢不叠加 |
| 工具一股脑全丢给 LLM | 按 workflow **沙箱隔离**，视频问答只能调视频相关工具 |
| 中间断电 = 全部重来 | **节点级 Checkpoint** + Resume API，从上次成功的步骤续跑 |
| 工具调用没有约束 | **Tool Governor** 限流 + 超时 + 全量 trace |
| 上下文一把梭 | **三层隔离**（短期流式缓冲 / 会话事实 / 长期记忆） |

**一句话总结**：VAgent = 视频平台 AI 助手 + Multi-Agent 并行架构 + 完整的可靠性基础设施（Agent Harness）。

---

## 🔒 安全性

- API Key 只走环境变量，不硬编码
- `.env` 已 `.gitignore`，不提交仓库
- `.env.example` 提供模板，不含真实密钥
- 用户数据查询走服务端 token 推导，不信任前端参数，防止越权
- Tool Governor 限流防止单用户拖垮系统
- 工具调用全量 trace，便于审计

## 📄 License

MIT
