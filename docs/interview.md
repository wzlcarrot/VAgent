# 面试提纲

ViewHub 上的 AI 助手：真实行为数据做推荐/问答，不是套壳 RAG。

## 演示（约 3 分钟）

登录 → 问当前视频讲什么（看路由 meta）→ 要类似推荐（看理由是否来自 tags/分区）→ 问「第二个讲什么」→ 问自己的点赞 → 点「没用」再推一次 → checkpoint 续跑。

## 可能被问到的点（自己讲，别背稿）

- 置信度：关键词 / 语义 / LLM 分歧，SSE 能看见 method。
- 并行：主意图 + chat 兜底两路，不是四路。
- 路由：`golden_set.py` 离线表 + pytest 下限。
- 推荐：ViewHub 真实 tags，负反馈会从候选剔除。
- 超时：`cancel_scope` 会 abort httpx / `conn.cancel`，不是干等。

## 现场命令

```bash
cd ai-end && python -m pytest tests/ -q --cov=app
cd ai-end && python scripts/golden_set.py --no-llm
cd ../ai-frontend && npx vitest run --coverage
```
