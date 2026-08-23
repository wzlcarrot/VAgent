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
- 意图路由：关键词 + 语义 + LLM 三阶段，决策实时可见（SSE meta 事件）

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

# 前端（statements/lines 75%）
cd ai-frontend && npx vitest run --coverage
```

## 面试叙事

面试提纲见 [docs/interview.md](docs/interview.md)。

## License

MIT
