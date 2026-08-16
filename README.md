<div align="center">

# VAgent

**ViewHub 的 AI 智能助手**

提供视频问答、个性化视频推荐、个人数据查询与平台使用帮助。

</div>

---

## 功能

- 视频内容智能问答
- 个性化 / 冷启动视频推荐
- 用户点赞、收藏、播放历史数据查询
- 平台使用帮助与客服对话
- 多轮对话与跨会话记忆

## 快速开始

### Docker Compose（推荐）

```bash
git clone https://github.com/wzlcarrot/VAgent.git
cd VAgent
cp .env.example .env      # 填入 LLM API Key
docker compose up -d --build
```

- 前端：http://localhost:4091
- API 文档：http://localhost:9090/docs

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

## 配置

核心配置项见 `.env.example`，主要包括：

- LLM Provider 与 API Key（DeepSeek / MiniMax）
- 数据库与 Redis 连接
- 测试账户开关（生产环境请关闭）

## 测试

```bash
# 后端
cd ai-end && python -m pytest tests/ -q

# 前端
cd ai-frontend && npx vitest run
```

## License

MIT
