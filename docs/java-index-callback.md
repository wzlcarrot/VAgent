# ViewHub Java → AI 索引回调（索引 SLA）

转码/入库成功后必须立刻回调 AI 建索引；AI 启动 backfill 与 `reindex-pending` 只是兜底，不能替代主路径。

## 何时调用

`video_info` 写入成功、转码完成、视频可播放之后 **立即** 调用。

不要：等用户第一次提问才索引；不要依赖 AI 进程重启补全。

## 请求

```http
POST {AI_BASE}/ai/admin/index-video/{videoId}
X-Admin-Key: <ADMIN_API_KEY>
```

Body 可空。`AI_BASE` 示例：`http://vagent:9090`（compose 内网）或对外网关地址。

### Java 伪代码

```java
// 转码成功回调 / 上传完成监听器内
HttpRequest req = HttpRequest.newBuilder()
    .uri(URI.create(aiBase + "/ai/admin/index-video/" + videoId))
    .header("X-Admin-Key", adminApiKey)
    .POST(HttpRequest.BodyPublishers.noBody())
    .timeout(Duration.ofSeconds(30))
    .build();
HttpResponse<String> resp = client.send(req, HttpResponse.BodyHandlers.ofString());
if (resp.statusCode() != 200 || !resp.body().contains("\"success\":true")) {
    // 记日志 + 重试（建议指数退避，最多 3 次）
}
```

## 成功响应示例

```json
{
  "success": true,
  "video_id": "1L6ZvY1EMm",
  "parts": {
    "title": {"indexed": true},
    "tags": {"indexed": true},
    "introduction": {"indexed": true},
    "subtitle": {
      "indexed": true,
      "segment_count": 42,
      "index_block_count": 12
    }
  }
}
```

`subtitle`：Python 侧 ASR（可选 `VIDEO_ASR_ENABLED`）写入 PostgreSQL 表 `video_subtitle_segment`，并索引为 `subtitle_*` 向量块（带真实 `start_s`）。未找到视频文件或未装 faster-whisper 时，`subtitle.indexed` 可能为 false，不影响 title/tags/introduction。

## 失败与重试

| 情况 | 处理 |
|------|------|
| HTTP 403 | Key 错误，修配置，不要盲重试 |
| HTTP 503 | `ADMIN_API_KEY` 未配或服务未就绪，稍后重试 |
| `success: false` | 查 `error` / `parts`；常见：视频不存在、embedding 失败 |
| 超时 / 5xx | 指数退避重试 3 次，仍失败进死信/运维告警 |

幂等：重复调用会先 `DELETE` 同类型旧块再写入，可安全重试。

## AI 侧兜底（不要当主路径）

1. 启动时 `reindex_pending(limit=50)`（`main.py` lifespan）
2. Admin：`POST /ai/admin/reindex-pending?limit=50`
3. 运维：`GET /ai/admin/index-stats`、质量看板「待索引」

## 产品行为（SLA）

- 未建索引的视频：视频内回答返回固定话术「知识库还在构建中」，**不瞎编**
- 目标：**转码完成后 1 分钟内** `is_video_indexed(video_id)=true`
- Admin「本周质量」：`videos_pending`、`indexed_ratio`、`pending_alert`

## 联调检查清单

- [ ] Java 配置了正确的 `AI_BASE` + `ADMIN_API_KEY`
- [ ] 上传一条新视频后 `GET /ai/admin/index-stats` pending 下降
- [ ] `POST /ai/admin/index-video/{id}` 可手工复现
- [ ] 未索引视频提问 → 拒答文案，不出现虚构细节
