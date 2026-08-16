import { interviewMode, http } from '@/config/api'
import type { SearchResult } from '@/types'

function getStreamUrl(path: string): string {
  // interviewMode 用于绕过 proxy 直连后端（调试用）
  // 默认使用相对路径 → 经由 vite proxy（开发）或 nginx（生产）转发到 Python 后端
  return interviewMode.enabled
    ? `${interviewMode.pythonApi}${path}`
    : path
}

export interface HistoryMessage {
  role: string
  content: string
  timestamp: string
  session_id?: string
  imageUrls?: string[]
  image_urls?: string[]  // 后端历史接口实际返回 snake_case
  videos?: Array<{
    videoId: string
    title: string
    cover?: string
    author?: string
    tags?: string[]
  }> | null
  reasons?: string[] | null
}

export async function getChatHistory(
  sessionId?: string,
  limit: number = 50
): Promise<HistoryMessage[]> {
  const params = new URLSearchParams()
  if (sessionId) params.append('session_id', sessionId)
  params.append('limit', limit.toString())

  const url = `${getStreamUrl('/ai/chat/history')}?${params.toString()}`

  const response = await http.get(url)
  return response.data.messages || []
}

export async function getChatSessions(
  limit: number = 20,
  offset: number = 0
): Promise<{ session_id: string; user_id: string; first_message_at: string; message_count: number; first_question: string }[]> {
  const params = new URLSearchParams()
  params.append('limit', limit.toString())
  params.append('offset', offset.toString())

  const url = `${getStreamUrl('/ai/chat/sessions')}?${params.toString()}`
  const response = await http.get(url)
  return response.data.sessions || []
}

export async function searchChatContent(
  q: string,
  limit: number = 50
): Promise<SearchResult[]> {
  const params = new URLSearchParams()
  params.append('q', q)
  params.append('limit', limit.toString())
  const url = `${getStreamUrl('/ai/chat/search')}?${params.toString()}`
  try {
    const response = await http.get(url)
    return response.data.results || []
  } catch {
    return []
  }
}

export async function deleteChatSession(sessionId: string): Promise<boolean> {
  const url = getStreamUrl(`/ai/chat/session/${sessionId}`)
  const response = await http.delete(url)
  return response.data?.success === true
}

export interface CheckpointStep {
  workflow_type: string
  steps: Array<{ step_name: string; created_at: string; status: string }>
  last_completed_step: string | null
  last_completed_at: string | null
}

export async function getCheckpoints(sessionId: string): Promise<{
  session_id: string
  checkpoints: CheckpointStep[]
}> {
  const params = new URLSearchParams()
  params.append('session_id', sessionId)
  const url = `${getStreamUrl('/ai/chat/checkpoints')}?${params.toString()}`
  const response = await http.get(url)
  return response.data
}

export async function submitFeedback(params: {
  session_id: string
  message_index: number
  feedback: 'helpful' | 'not_helpful'
}): Promise<{ success: boolean }> {
  const url = getStreamUrl('/ai/feedback')
  const response = await http.post(url, params)
  return response.data
}

export type StreamStatusEvent = {
  type: 'status'
  stage: string
  label: string
}

export type StreamTextEvent = {
  type: 'text'
  content: string
}

export type StreamVideosEvent = {
  type: 'videos'
  videos: Array<{
    videoId: string
    title: string
    cover?: string
    author?: string
    tags?: string[]
  }>
  reasons: string[]
}

export type StreamEvent = StreamStatusEvent | StreamTextEvent | StreamVideosEvent

export type ParsedSSELine =
  | { kind: 'done' }
  | { kind: 'event'; event: StreamEvent }
  | { kind: 'text'; content: string }

/**
 * 解析单行 SSE（`data: ...`）为结构化事件。
 *
 * 规则：
 * - 非 `data:` 前缀 → null（忽略）
 * - 空数据 / `[DONE]` → done 哨兵（终止流）
 * - 合法 JSON 且含 type → 对应事件；videos/reasons 缺省时兜底为 []
 * - JSON 解析失败且以 `{`/`[` 开头 → null（半截 chunk，跳过）
 * - 其他纯文本 → 作为 text 事件输出
 */
export function parseSSELine(line: string): ParsedSSELine | null {
  if (!line.startsWith('data: ')) return null
  const data = line.slice(6).trim()
  if (!data) return null
  if (data === '[DONE]') return { kind: 'done' }
  try {
    const parsed = JSON.parse(data)
    if (parsed && typeof parsed === 'object' && parsed.type) {
      if (parsed.type === 'status') {
        return {
          kind: 'event',
          event: { type: 'status', stage: parsed.stage, label: parsed.label },
        }
      }
      if (parsed.type === 'text') {
        return {
          kind: 'event',
          event: { type: 'text', content: typeof parsed.content === 'string' ? parsed.content : '' },
        }
      }
      if (parsed.type === 'videos') {
        return {
          kind: 'event',
          event: { type: 'videos', videos: parsed.videos || [], reasons: parsed.reasons || [] },
        }
      }
    }
    return null
  } catch {
    if (data.startsWith('{') || data.startsWith('[')) {
      console.warn('[SSE] 非预期 JSON:', data)
      return null
    }
    return { kind: 'text', content: data }
  }
}

export function triggerUnauthorized() {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('auth:unauthorized'))
  }
}

export async function* smartChatStream(
  message: string,
  sessionId?: string,
  videoId?: string,
  userId?: string,
  token?: string,
  imageUrls?: string[],
  signal?: AbortSignal
): AsyncGenerator<StreamEvent, void, unknown> {
  const url = getStreamUrl('/ai/chat/stream')

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const body: Record<string, unknown> = { question: message, sessionId, video_id: videoId, user_id: userId }
  if (imageUrls && imageUrls.length > 0) {
    body.image_urls = imageUrls
  }

  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal,
    // 携带 httpOnly auth_token cookie（同源默认带；include 兼容跨源直连）
    credentials: 'include',
  })

  if (!response.ok) {
    if (response.status === 401) {
      // token 过期，清理并跳转登录页
      try { localStorage.removeItem('user') } catch {}
      triggerUnauthorized()
    }
    throw new Error(`HTTP ${response.status}`)
  }

  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error('No response body')
  }

  const decoder = new TextDecoder()
  let buffer = ''
  // 防 DoS：单帧最大 1MB，超过直接报错终止流
  const MAX_BUFFER_SIZE = 1024 * 1024

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    if (buffer.length > MAX_BUFFER_SIZE) {
      reader.cancel()
      throw new Error('SSE buffer overflow (>1MB without newline)')
    }
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      const parsed = parseSSELine(line)
      if (parsed === null) continue
      if (parsed.kind === 'done') return  // [DONE] 终止流
      if (parsed.kind === 'event') {
        yield parsed.event
      } else {
        yield { type: 'text', content: parsed.content }
      }
    }
  }

  // Flush remaining buffer（流结束但末尾没有换行符）
  if (buffer.trim()) {
    for (const line of buffer.split('\n')) {
      const parsed = parseSSELine(line)
      if (parsed === null) continue
      if (parsed.kind === 'done') return
      if (parsed.kind === 'event') {
        yield parsed.event
      } else {
        yield { type: 'text', content: parsed.content }
      }
    }
  }
}
