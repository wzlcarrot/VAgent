# 架构决策记录（ADR）

本文档记录关键架构决策的背景、权衡与迁移路径，供维护者快速理解设计意图。

## ADR-001：Workflow 用线程池执行同步 LangGraph，而非原生全异步

**状态**：已采纳（2026）

### 背景

4 路 workflow（video_qa / recommend / user_data / chat_graph）由 LangGraph 驱动，节点内部调用：
- 同步 psycopg2 数据库访问
- 同步 `LLM_tools.chat_sync`（httpx 同步 client）
- 同步 Redis 访问

### 决策

将整个 workflow 作为**同步函数**提交到进程级线程池（`run_sync_in_executor`，`AGENT_ASYNC_MAX_WORKERS` 默认 8），在 async 路由中通过 `asyncio.gather` 并行等待。路由层（FastAPI）保持全异步。

```
async chat_stream
  └─ asyncio.gather(                       # 并行派发
       await run_sync_in_executor(video_qa_workflow, ..., timeout=120)
       await run_sync_in_executor(chat_workflow,    ..., timeout=120)
     )
```

### 权衡

**为什么不用全原生异步（asyncpg / redis.asyncio / 异步 LangGraph）？**

| 维度 | 线程池方案（当前） | 全异步方案 |
|------|------------------|-----------|
| 迁移成本 | 现状 | 全部工具层改 async 驱动，LangGraph 节点改 async，工作量大且风险高 |
| 开发心智 | 同步代码简单直观 | async 传染性强，需处理所有 I/O |
| 单请求延迟 | 等效 | 等效 |
| 高并发吞吐 | 受线程池上限约束 | 可扩展到 event loop 极限 |
| 资源占用 | 每请求占 1-2 线程 | 协程级，内存占用低 |

**本项目的定位**：单实例演示/中低并发场景。线程池方案在并发 < 线程池容量时与全异步几乎无差，且代码可维护性更高。事件循环本身永不阻塞（所有同步 I/O 均在 executor 线程执行），已用并发测试验证。

### 已落地的防护

- **超时保护**：`run_sync_in_executor` 支持 `timeout`，workflow 执行 120s 超时降级，防止卡死调用永久占用线程。
- **可配置容量**：`AGENT_ASYNC_MAX_WORKERS`（默认 8，可调）。
- **优雅关闭**：lifespan shutdown 时显式关闭所有 executor（agent_async / checkpoint / tool_governor / chat_recall / recall）。

### 迁移路径（如果未来需要）

1. DB：psycopg2 → asyncpg / SQLAlchemy async（连接池复用现有 `get_global_pool` 语义）
2. Redis：redis-py → redis.asyncio
3. LangGraph：节点改 `async def` + `graph.ainvoke`/`astream`
4. 完成后移除线程池方案，路由直接 `await` workflow

## ADR-002：token 存放于 httpOnly cookie，而非 localStorage

**状态**：已采纳（2026）

### 决策

登录后 token 写入 `httpOnly + SameSite=Lax` cookie；前端 localStorage 仅存非敏感用户信息（昵称/头像/uid），不再存 token。`Authorization: Bearer` header 保留用于非浏览器客户端。

### 理由

- **XSS 面**：localStorage 可被任意 XSS 读取；httpOnly cookie 对 JS 不可见。
- **CSRF 缓解**：`SameSite=Lax` 使跨站 POST 不携带 cookie；本项目变更接口均为 POST。
- **向后兼容**：header 路径保留，API 测试/工具不受影响。

## ADR-003：错误消息统一防用户枚举

**状态**：已采纳（2026）

登录失败统一返回"邮箱或密码错误"，且邮箱不存在时不执行 bcrypt 校验（响应时间接近），避免通过错误消息或时序差异枚举有效邮箱。

## ADR-004：RAG 内容进 prompt 前统一转义

**状态**：已采纳（2026）

所有 workflow 将 RAG 召回内容拼入 system prompt 前，复用 `ranker.safe_prompt_escape`（剥离 ``` / --- / <| / ###）+ system prompt 防御指令，缓解检索内容注入（prompt injection）。
