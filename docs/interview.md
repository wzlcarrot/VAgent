# 面试提纲

ViewHub 上的 AI 助手：真实行为数据做推荐/问答，不是套壳 RAG。

## 演示（约 3 分钟）

打开带当前视频的入口（`http://localhost:4091/?video=<id>`，从 ViewHub 播放页带参跳入）
→ 问当前视频讲什么（看路由 meta：`视频问答 · 置信度 60%+`）→ 要类似推荐（看理由是否来自 tags/分区）→ 问「第二个讲什么」→ 问自己的点赞 → 点「没用」再推一次 → checkpoint 续跑。

> 视频上下文用 URL `?video=<id>` 带入：前端优先用问题里贴的 `id:xxx`，否则回退 URL 的当前视频。
> 演示第一句「这个视频讲了什么」必须带上 video_id，否则路由虽判 video_qa，澄清器仍会追问视频来源。

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

## 演示环境注意（会挂的地方）

- **前端必须走同源/代理访问后端**（compose 的 `:4091` 经 nginx，或 Vite dev 的 proxy）。
  登录 cookie 是 `SameSite=Lax` + `httpOnly`，Vite 直连 `:9090` 属跨站，现代浏览器不种/不带第三方 cookie，刷新后 401。别在演示时用 `VITE_INTERVIEW_MODE=true` + 直连 `:9090`。
- 推荐卡片字段：前端对实时流已统一 `normalizeVideos`（snake→camel），后端推 `video_id` 即可，无需改契约。
- 新用户第一次说「推荐」会触发澄清器追问类别；问题里写明「科技/AI/美食」等类别词则直接推荐。
- 本地 embedding 模型加载失败会降级 hash 并打 warning（语义路由自动降为纯关键词），属环境问题不是逻辑错误。
