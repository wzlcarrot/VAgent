# VAgent

面向视频平台的 Multi-Agent AI 助手：视频问答、推荐、数据查询、智能客服。

技术栈：FastAPI + LangGraph + Vue 3 + PostgreSQL (pgvector / ParadeDB) + Redis

## 快速开始

```bash
git clone https://github.com/wzlcarrot/VAgent.git
cd VAgent
cp ai-end/.env.example ai-end/.env   # 填入 DEEPSEEK_API_KEY（必填）
docker compose up -d
```

- 前端：http://localhost:5174
- API：http://localhost:9090
- 文档：http://localhost:9090/docs

## 本地开发

```bash
# 后端
cd ai-end && pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8001

# 前端
cd ai-frontend && npm install && npm run dev
```

## License

MIT
