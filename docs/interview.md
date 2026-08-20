# 面试叙事 & 演示剧本

> 目的：这套项目怎么讲、怎么被追问、怎么演示。目标是让面试官问不倒。

---

## 一句话定位

**一个深度接入 ViewHub 真实数据的 AI 助手**：意图路由（关键词+语义+LLM 三阶段）、主流程与兜底并行执行、推荐基于主站真实行为画像（tags/分区/点赞/收藏/完播）、跨会话记忆 + 赞踩影响下次排序、可断点续跑的 checkpoint、超时能真正掐断下游 I/O。

不是"套壳 RAG demo"，是"长在真实产品数据上、每一步决策可见"的 agent。

---

## 三分钟闭环演示剧本

开场用一个真实场景串起所有亮点。准备：登录测试账号、一部正在看的视频。

| 步骤 | 操作 | 展示点 | 对应追问话术 |
|---|---|---|---|
| 1 | 点开一个视频，问"这个视频讲了什么" | 路由 meta 事件显示 `视频问答 · 关键词+语义一致 · 置信度 87%` | 置信度哪来的？→ 见 P0-1 |
| 2 | 问"推荐两个类似的" | 推荐理由显示"你常看「AI」· 你点过同类" | 画像哪来的？→ 见 P1-1 |
| 3 | 问"第二个讲什么" | 上下文把"第二个"解析成上一条推荐的第二个视频 | 指代消解 → 见下文 |
| 4 | 问"我点赞了哪些视频" | 路由到个人数据，SSE 显示 `个人数据 · 关键词+语义一致` | 四类意图怎么分的？→ 见 P0-2 |
| 5 | 对一条推荐点"没用" | 下次同类问题不再推荐该视频 | 赞踩怎么生效？→ 见 P1-2 |
| 6 | 打开 checkpoint 面板点"继续运行" | 从断点恢复跑完 | checkpoint 怎么存/恢复？→ 见下文 |

---

## 可追问点 × 标准答案

### P0-1 置信度是真信号，不是写死
- 追问：**"置信度 0.9 哪来的？"**
- 答：`Router.hybrid_route_full` 返回 `RouteDecision(workflow_type, confidence, method)`。置信度是合成信号：
  - `keyword_only`：关键词命中强度（`route_candidates` 的固定分）
  - `consensus`：关键词 Top-1 与语义 Top-1 一致时取 `max(关键词分, 语义余弦归一化分)`
  - `llm`：分歧时 LLM 裁决，置信度 `max(语义, 关键词, 0.7)`
  - 兜底（chat）固定 0.5，明显低于主意图
- 佐证：SSE 有 `meta` 事件，前端 WorkflowIndicator 显示 `意图 · 方法 · 置信度`。现场能指着屏幕讲"这条是关键词和语义一致，没调 LLM"。

### P0-2 并行是"主流程 + chat 兜底"两路，不吹四路
- 追问：**"不是说四路并行吗？"**
- 答：诚实讲——`parallel_agent_pipeline` 跑的是 `[主意图] + [chat 兜底]` 两路，`asyncio.gather` 并发，延迟取 max。真正的并行点还有两个：
  - 双路召回：BM25 ∥ 向量（`ranker.dual_recall_and_rerank`）
  - chat 的 3 路知识召回
- 亮点：不夸大，反而显得架构克制。面试官喜欢知道"哪些是真实并行、哪些只是顺序"。

### P0-3 路由决策透明化
- 追问：**"怎么证明路由在起作用？"**
- 答：三个证据链：
  1. `scripts/golden_set.py`：75 条用例（含歧义/离题句），离线跑关键词单路 84%；分方法命中表 `关键词(单路)/融合·共识/融合·兜底/融合(整体)` 一张表打出来。
  2. 黄金集已进 pytest（`tests/test_golden_set.py`，基线 ≥75%），改路由关键词逻辑会无感退化 → CI 拦。
  3. UI meta 事件实时展示 winner + method + confidence。

### P0-4 Checkpoint 能演示，不只是名词
- 追问：**"checkpoint 怎么恢复？"**
- 答：`workflow_checkpoints` 表按 `(session, workflow, step)` 存每步状态快照；`/ai/chat/resume` 从 `last_completed_step` 的下一节点继续跑，恢复的是中间 state 不是重头来。UI 的 CheckpointViewer 有"继续运行"按钮，现场演示中断→续跑。

### P1-1 推荐画像用 ViewHub 真实行为
- 追问：**"推荐理由怎么来的？"**
- 答：`profile_node` 取 watched/liked/favorited 的 video_id → `VideoTools.get_video_info_batch` 反查真实 `tags` + `category_id`（分区）→ 生成画像 `favorite_tags`/`favorite_regions`。`reason_node` 据此写理由："你常看「AI」· 你点过同类"。**不是**把视频标题按空格切分。
- 佐证：`video_info` 表有 `tags`/`category_id`，真实信号；测试 `test_builds_profile` 断言 tags 来自 VideoInfo 反查。

### P1-2 记忆 + 赞踩真正影响下次排序
- 追问：**"记忆/反馈只写表不生效？"**
- 答：三条链路全部打通：
  1. `recall_memories` 用 pg_trgm `%` 运算符 + GIN 索引（`idx_user_memory_content_trgm`）召回偏好/活动记忆，并入推荐 query。
  2. 前端"有用/没用"按钮（`MessageBubble.vue`）→ `submitFeedback` 带 `video_ids` → 记忆 tags 存 `video:<id>`。
  3. `search_node` 调 `get_negative_feedback_video_ids` 把负反馈视频从候选剔除。
- 佐证：`tests/test_memory_recall.py` 有真实 DB 断言；`test_rag_tools`/`test_llm_tools_http` 覆盖索引与召回路径。

### A4 超时是真掐断，不是干等
- 追问：**"Python 杀不了线程，超时怎么处理？"**
- 答：`task_cancel.cancel_scope` + `register_abortable`：超时后 `event.set()`，并调用已注册的 abortable——`httpx.Client.close()`、`psycopg2 connection.cancel()`——**真正打断正在阻塞的下游 I/O**。重试循环里 `check_cancelled()`/`interruptible_sleep` 快速退出。`run_sync_in_executor` 挂 `cancel_scope`，`get_cursor` 注册 `conn.cancel`，链路完整。
- 佐证：`tests/test_task_cancel.py` 断言 `conn.cancel` 被调用。

### A3 安全默认
- 追问：**"安全上做了哪些？"**
- 答：`TEST_ACCOUNT_ENABLED` 默认 false；`POSTGRES_PASSWORD`/`ADMIN_API_KEY` compose 强制设置（`?` 报错拒绝默认值）；`/metrics` 与 `/ai/admin` 走 X-Admin-Key fail-closed；登录按 IP 滑动窗口限流（10 次/15 分钟）；prometheus 镜像固定版本 + 模板渲染注入 key（不留明文）。

### 覆盖率 75% 怎么来的
- 追问：**"覆盖率是不是挑着算的？"**
- 答：**不挑。** `pyproject.toml` 不再 omit 任何文件，`--cov=app` 全量算，门槛 75%。LLM/rag 这类依赖网络的大文件用 httpx mock + 连接池 mock 真实覆盖（`test_llm_tools_http.py` 63 用例、`test_rag_tools.py` 覆盖 BM25/向量/FAQ/索引），不是排除掉。前端 statements 75% / lines 80% / branches 55%。

---

## 数据验证脚本（现场可跑）

```bash
# 后端（需 DB + LLM key，CI 已有 postgres 服务）
cd ai-end
python -m pytest tests/ -q --cov=app          # 417 passed, 75.4%
ruff check app tests scripts

# 路由黄金集（离线，不调 LLM）
python scripts/golden_set.py --no-llm          # 分方法命中表
python scripts/golden_set.py --limit 20 --no-llm

# 双路召回对比（需 DB）
python scripts/ablate_recall.py --top-k 5

# 前端
cd ../ai-frontend
npx vitest run --coverage                      # 144 passed, 77%
npx vue-tsc --noEmit
```

---

## 架构一张图（口述）

```
用户问题
  └─ Router.hybrid_route_full（关键词 ⊕ 语义 ⊕ LLM 裁决 → RouteDecision）
       └─ parallel_agent_pipeline（asyncio.gather）
            ├─ 主意图 workflow（video_qa / recommend / user_data）
            └─ chat 兜底
                 └─ Supervisor.arbitrate（优先级 × 置信度 × 非空）
                      └─ meta 事件 → 前端展示 winner/method/confidence
                 └─ 输出流式回复 + 推荐卡片（跳回 ViewHub 播放）

Recommend workflow 内部：
  profile_node（ViewHub 真实 tags/分区/点赞/收藏）
    → search_node（画像 + 记忆 + 负反馈剔除 → 双路召回 BM25∥向量）
      → rerank → reason_node（"你常看X·你点过同类"）
```

每层都有 checkpoint（可续跑）+ 可取消（task_cancel 掐断 I/O）+ 指标（Prometheus）。
