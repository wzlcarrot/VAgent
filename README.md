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

```bash
git clone https://github.com/wzlcarrot/VAgent.git
cd VAgent
cp .env.example .env      # 填 LLM API Key + 强 POSTGRES_PASSWORD / ADMIN_API_KEY
docker compose up -d --build
```

- 前端：http://localhost:4091
- API 文档：http://localhost:9090/docs

> 生产安全默认：测试账户关闭、数据库口令/管理 key 强制设置、/metrics 鉴权、登录限流。

## 测试

```bash
# 后端（覆盖率门槛 75%，无 omit）
cd ai-end && python -m pytest tests/ -q --cov=app

# 路由黄金集（离线，分方法命中表）
cd ai-end && python scripts/golden_set.py --no-llm

# 双路召回对比（BM25-only / vector-only / 融合）
cd ai-end && python scripts/ablate_recall.py --top-k 5

# 前端（statements/lines 75%）
cd ai-frontend && npx vitest run --coverage
```

## 面试叙事

工程亮点、可追问点的标准回答、三分钟演示剧本见 [docs/interview.md](docs/interview.md)。

## License

MIT
