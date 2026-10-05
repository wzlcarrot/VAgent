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
  citations?: Array<{
    id: number
    snippet: string
    score?: number
    block_type?: string
    video_id?: string
  }> | null
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
  video_ids?: string[]
  question?: string
  answer?: string
  workflow_type?: string
  reason?: string
}): Promise<{ success: boolean; weekly_golden?: Record<string, unknown>; suggest_rebatch?: boolean }> {
  const url = getStreamUrl('/ai/feedback')
  const response = await http.post(url, params)
  return response.data
}

export async function trackRecommendClick(params: {
  video_id: string
  session_id?: string
  source?: string
}): Promise<void> {
  const url = getStreamUrl('/ai/analytics/recommend-click')
  await http.post(url, params)
}

export async function submitApproval(params: {
  approval_id: string
  decision: 'approve' | 'deny'
  session_id?: string
}): Promise<{ ok: boolean; decision?: string }> {
  const url = getStreamUrl(`/ai/approval/${encodeURIComponent(params.approval_id)}`)
  const response = await http.post(url, {
    decision: params.decision,
    session_id: params.session_id || '',
  })
  return response.data
}

export async function resumeWorkflow(sessionId: string): Promise<{
  success: boolean
  workflow_type: string
  resumed_from: string
  answer: string
  error?: string | null
  failed_at?: string | null
}> {
  const url = getStreamUrl('/ai/chat/resume')
  const response = await http.post(url, { session_id: sessionId })
  return response.data
}

export interface TraceRun {
  run_id: string
  started_at?: number
  status: string
  event_count: number
}

export async function getSessionTraces(sessionId: string): Promise<{
  session_id: string
  runs: TraceRun[]
}> {
  const params = new URLSearchParams()
  params.append('session_id', sessionId)
  const url = `${getStreamUrl('/ai/chat/traces')}?${params.toString()}`
  const response = await http.get(url)
  return response.data
}

export async function getSessionTrace(sessionId: string, runId: string): Promise<{
  session_id: string
  run_id: string
  events: Array<{ seq: number; type: string; payload: Record<string, unknown> }>
}> {
  const params = new URLSearchParams()
  params.append('session_id', sessionId)
  const url = `${getStreamUrl(`/ai/chat/traces/${runId}`)}?${params.toString()}`
  const response = await http.get(url)
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

export type StreamCitationsEvent = {
  type: 'citations'
  citations: Array<{
    id: number
    snippet: string
    score?: number
    block_type?: string
    video_id?: string
  }>
}

export type StreamMetaEvent = {
  type: 'meta'
  meta: {
    winner_type: string
    confidence: number
    method: string
  }
}

export type StreamToolEvent = {
  type: 'tool'
  name: string
  status: 'start' | 'end' | string
  label: string
  ok?: boolean
  duration_ms?: number
}

export type HarnessEvent = {
  type: 'harness'
  event: string
  payload: Record<string, unknown>
}

export type StreamRetryEvent = {
  type: 'retry'
  op: string
  next_attempt: number
  max_attempts: number
  wait_s: number
  status_code?: number
  error_type?: string
}

export type StreamApprovalEvent = {
  type: 'approval'
  approval_id: string
  tool: string
  label: string
  agent: string
  arguments_preview: string
  timeout_s: number
}

export type StreamEvent =
  | StreamStatusEvent
  | StreamTextEvent
  | StreamVideosEvent
  | StreamCitationsEvent
  | StreamMetaEvent
  | StreamToolEvent
  | StreamRetryEvent
  | StreamApprovalEvent
  | HarnessEvent

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
      if (parsed.type === 'citations') {
        const raw = Array.isArray(parsed.citations) ? parsed.citations : []
        return {
          kind: 'event',
          event: {
            type: 'citations',
            citations: raw.map((c: Record<string, unknown>, i: number) => ({
              id: typeof c?.id === 'number' ? c.id : i + 1,
              snippet: typeof c?.snippet === 'string' ? c.snippet : '',
              score: typeof c?.score === 'number' ? c.score : undefined,
              block_type: typeof c?.block_type === 'string' ? c.block_type : undefined,
              video_id: typeof c?.video_id === 'string' ? c.video_id : undefined,
              start_s: typeof c?.start_s === 'number' ? c.start_s : undefined,
              end_s: typeof c?.end_s === 'number' ? c.end_s : undefined,
            })).filter((c: { snippet: string }) => c.snippet),
          },
        }
      }
      if (parsed.type === 'meta') {
        const m = parsed.meta || {}
        return {
          kind: 'event',
          event: {
            type: 'meta',
            meta: {
              winner_type: typeof m.winner_type === 'string' ? m.winner_type : '',
              confidence: typeof m.confidence === 'number' ? m.confidence : 0,
              method: typeof m.method === 'string' ? m.method : '',
            },
          },
        }
      }
      if (parsed.type === 'tool') {
        return {
          kind: 'event',
          event: {
            type: 'tool',
            name: typeof parsed.name === 'string' ? parsed.name : '',
            status: typeof parsed.status === 'string' ? parsed.status : '',
            label: typeof parsed.label === 'string' ? parsed.label : '',
            ok: typeof parsed.ok === 'boolean' ? parsed.ok : undefined,
            duration_ms: typeof parsed.duration_ms === 'number' ? parsed.duration_ms : undefined,
          },
        }
      }
      if (parsed.type === 'retry') {
        return {
          kind: 'event',
          event: {
            type: 'retry',
            op: typeof parsed.op === 'string' ? parsed.op : '',
            next_attempt: typeof parsed.next_attempt === 'number' ? parsed.next_attempt : 0,
            max_attempts: typeof parsed.max_attempts === 'number' ? parsed.max_attempts : 0,
            wait_s: typeof parsed.wait_s === 'number' ? parsed.wait_s : 0,
            status_code: typeof parsed.status_code === 'number' ? parsed.status_code : undefined,
            error_type: typeof parsed.error_type === 'string' ? parsed.error_type : undefined,
          },
        }
      }
      if (parsed.type === 'approval') {
        return {
          kind: 'event',
          event: {
            type: 'approval',
            approval_id: typeof parsed.approval_id === 'string' ? parsed.approval_id : '',
            tool: typeof parsed.tool === 'string' ? parsed.tool : '',
            label: typeof parsed.label === 'string' ? parsed.label : '',
            agent: typeof parsed.agent === 'string' ? parsed.agent : '',
            arguments_preview: typeof parsed.arguments_preview === 'string' ? parsed.arguments_preview : '',
            timeout_s: typeof parsed.timeout_s === 'number' ? parsed.timeout_s : 60,
          },
        }
      }
      if (parsed.type === 'harness') {
        return {
          kind: 'event',
          event: {
            type: 'harness',
            event: typeof parsed.event === 'string' ? parsed.event : '',
            payload: (parsed.payload && typeof parsed.payload === 'object') ? parsed.payload : {},
          },
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

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const t = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      clearTimeout(t)
      reject(new DOMException('Aborted', 'AbortError'))
    }, { once: true })
  })
}

async function parseStreamBusy(response: Response): Promise<{ position: number; retryAfter: number; retryable: boolean }> {
  const headerRetry = Number(response.headers.get('Retry-After') || 0)
  let position = 1
  let retryAfter = headerRetry > 0 ? headerRetry : 2
  let retryable = false
  try {
    const data = await response.json()
    const detail = data?.detail ?? data
    if (detail && typeof detail === 'object') {
      const busy = detail as { error?: string; queue_position?: number; retry_after?: number }
      // 只有并发排队（stream_busy）才重试。频率限制的 429 再请求会计入限额，不能当排队。
      retryable = busy.error === 'stream_busy' || typeof busy.queue_position === 'number'
      if (typeof busy.queue_position === 'number') position = busy.queue_position
      if (typeof busy.retry_after === 'number') retryAfter = busy.retry_after
    }
  } catch {
    /* ignore */
  }
  return { position, retryAfter: Math.max(1, Math.min(30, retryAfter)), retryable }
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

  const maxBusyRetries = 4
  let response: Response | null = null
  for (let attempt = 0; attempt <= maxBusyRetries; attempt++) {
    response = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal,
      credentials: 'include',
    })

    if (response.ok) break

    if (response.status === 401) {
      try { localStorage.removeItem('user') } catch {}
      triggerUnauthorized()
      throw new Error('HTTP 401')
    }

    if (response.status === 429 && attempt < maxBusyRetries) {
      const { position, retryAfter, retryable } = await parseStreamBusy(response)
      if (!retryable) {
        throw new Error('请求过于频繁，请稍后再试')
      }
      yield {
        type: 'status',
        stage: 'queued',
        label: `服务繁忙，排队第 ${position} 位，${retryAfter}s 后重试…`,
      }
      await sleep(retryAfter * 1000, signal)
      continue
    }

    throw new Error(
      response.status === 429
        ? '服务繁忙，请稍后再试'
        : `HTTP ${response.status}`,
    )
  }

  if (!response || !response.ok) {
    throw new Error('HTTP request failed')
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
