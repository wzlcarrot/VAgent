/** 推荐视频归一化：DB 存量是 snake_case（video_id），实时流也可能 snake_case，
 * 统一成 camelCase（videoId），保证卡片 key / 理由 / 播放链接 / 负反馈一致。 */

export interface NormalizedVideo {
  videoId: string
  title: string
  cover: string
  author: string
  tags: string[]
}

export function normalizeVideos(videos: any[] | null | undefined): NormalizedVideo[] {
  if (!Array.isArray(videos)) return []
  return videos.map(v => ({
    videoId: v.videoId ?? v.video_id ?? '',
    title: v.title ?? '',
    cover: v.cover ?? '',
    author: v.author ?? '',
    tags: normalizeTags(v.tags),
  }))
}

const _VIDEO_ID_PATTERNS = [
  // video_id: / video-id: / 视频id: 形式（video 前缀优先，避免 `\bid` 误吃 video 里的 vid）
  /video[_-]?\s?id[号是:：\s]*([\w-]+)/i,
  // 裸 id:xxx（词边界，避免匹配到 video_id 里的 id）
  /\bid[号是:：\s]*([\w-]+)/i,
  // 视频id:xxx（必须紧跟 id，不能隔着空格——否则「视频 2024年出的」会误抽出 2024）
  /视频\s*id[号是:：\s]*([\w-]+)/i,
]

function _extractVideoIdFromText(text: string): string | null {
  for (const pattern of _VIDEO_ID_PATTERNS) {
    const m = text.match(pattern)
    if (m && m[1] && m[1].length >= 4) return m[1]
  }
  return null
}

/** 解析要传给后端的 video_id：优先取问题里贴的 ID，否则用 URL 带入的当前视频。 */
export function resolveVideoId(questionText: string, urlVideoId: string | null | undefined): string | undefined {
  const fromText = _extractVideoIdFromText(questionText)
  if (fromText) return fromText
  if (urlVideoId) return urlVideoId
  return undefined
}

function normalizeTags(tags: unknown): string[] {
  if (Array.isArray(tags)) {
    return tags.map(t => String(t)).filter(Boolean)
  }
  if (typeof tags === 'string' && tags.trim()) {
    return tags.split(',').map(t => t.trim()).filter(Boolean)
  }
  return []
}
