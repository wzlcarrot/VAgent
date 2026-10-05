import { describe, it, expect, vi, afterEach } from 'vitest'
import { parseSSELine, smartChatStream } from '@/api/chat'

describe('parseSSELine', () => {
  it('忽略非 data: 行', () => {
    expect(parseSSELine('ping: keepalive')).toBeNull()
    expect(parseSSELine('event: text')).toBeNull()
    expect(parseSSELine('')).toBeNull()
  })

  it('空 data 返回 null', () => {
    expect(parseSSELine('data: ')).toBeNull()
    expect(parseSSELine('data:   ')).toBeNull()
  })

  it('[DONE] 返回 done 哨兵', () => {
    expect(parseSSELine('data: [DONE]')).toEqual({ kind: 'done' })
  })

  it('解析 status 事件', () => {
    expect(parseSSELine('data: {"type":"status","stage":"routing","label":"分析意图"}')).toEqual({
      kind: 'event',
      event: { type: 'status', stage: 'routing', label: '分析意图' },
    })
  })

  it('解析 text 事件', () => {
    expect(parseSSELine('data: {"type":"text","content":"你好"}')).toEqual({
      kind: 'event',
      event: { type: 'text', content: '你好' },
    })
  })

  it('解析 videos 事件，reasons 缺省时兜底为空数组', () => {
    expect(parseSSELine('data: {"type":"videos","videos":[{"videoId":"v1"}]}')).toEqual({
      kind: 'event',
      event: { type: 'videos', videos: [{ videoId: 'v1' }], reasons: [] },
    })
  })

  it('videos 为 null 时兜底为空数组（防前端 forEach 崩溃）', () => {
    expect(parseSSELine('data: {"type":"videos","videos":null}')).toEqual({
      kind: 'event',
      event: { type: 'videos', videos: [], reasons: [] },
    })
  })

  it('保留 videos 事件已有的 reasons', () => {
    const line = 'data: {"type":"videos","videos":[],"reasons":["理由A"]}'
    expect(parseSSELine(line)).toEqual({
      kind: 'event',
      event: { type: 'videos', videos: [], reasons: ['理由A'] },
    })
  })

  it('解析 citations 事件，缺省时兜底为空数组', () => {
    expect(parseSSELine('data: {"type":"citations"}')).toEqual({
      kind: 'event',
      event: { type: 'citations', citations: [] },
    })
  })

  it('解析 citations 事件并规范化字段（含 start_s）', () => {
    const line = 'data: {"type":"citations","citations":[{"id":1,"snippet":"证据A","score":0.9,"block_type":"introduction_0","video_id":"v1","start_s":12.5,"end_s":40}]}'
    expect(parseSSELine(line)).toEqual({
      kind: 'event',
      event: {
        type: 'citations',
        citations: [{
          id: 1, snippet: '证据A', score: 0.9, block_type: 'introduction_0',
          video_id: 'v1', start_s: 12.5, end_s: 40,
        }],
      },
    })
  })

  it('citations 无 snippet 的项被过滤', () => {
    const line = 'data: {"type":"citations","citations":[{"id":1,"snippet":""},{"snippet":"ok"}]}'
    expect(parseSSELine(line)).toEqual({
      kind: 'event',
      event: {
        type: 'citations',
        citations: [{
          id: 2, snippet: 'ok', score: undefined, block_type: undefined,
          video_id: undefined, start_s: undefined, end_s: undefined,
        }],
      },
    })
  })

  it('解析 meta 事件（路由决策）', () => {
    const line = 'data: {"type":"meta","meta":{"winner_type":"recommend_workflow","confidence":0.85,"method":"consensus"}}'
    expect(parseSSELine(line)).toEqual({
      kind: 'event',
      event: {
        type: 'meta',
        meta: { winner_type: 'recommend_workflow', confidence: 0.85, method: 'consensus' },
      },
    })
  })

  it('解析 tool 事件（工具进度）', () => {
    const line = 'data: {"type":"tool","name":"search_video_chunks","status":"start","label":"检索视频片段"}'
    expect(parseSSELine(line)).toEqual({
      kind: 'event',
      event: {
        type: 'tool',
        name: 'search_video_chunks',
        status: 'start',
        label: '检索视频片段',
        ok: undefined,
      },
    })
  })

  it('解析 tool end 事件含 duration_ms', () => {
    const line = 'data: {"type":"tool","name":"search_video_chunks","status":"end","label":"检索视频片段","ok":true,"duration_ms":42}'
    expect(parseSSELine(line)).toEqual({
      kind: 'event',
      event: {
        type: 'tool',
        name: 'search_video_chunks',
        status: 'end',
        label: '检索视频片段',
        ok: true,
        duration_ms: 42,
      },
    })
  })

  it('解析 approval HITL 事件', () => {
    const line = 'data: {"type":"approval","approval_id":"a1","tool":"recommend_videos","label":"个性化推荐","agent":"recommend_workflow","arguments_preview":"{}","timeout_s":60}'
    expect(parseSSELine(line)).toEqual({
      kind: 'event',
      event: {
        type: 'approval',
        approval_id: 'a1',
        tool: 'recommend_videos',
        label: '个性化推荐',
        agent: 'recommend_workflow',
        arguments_preview: '{}',
        timeout_s: 60,
      },
    })
  })

  it('meta 字段缺失时兜底为安全默认值', () => {
    const line = 'data: {"type":"meta"}'
    expect(parseSSELine(line)).toEqual({
      kind: 'event',
      event: { type: 'meta', meta: { winner_type: '', confidence: 0, method: '' } },
    })
  })

  it('meta 字段类型异常时兜底为安全默认值', () => {
    const line = 'data: {"type":"meta","meta":{"winner_type":123,"confidence":"x","method":null}}'
    expect(parseSSELine(line)).toEqual({
      kind: 'event',
      event: { type: 'meta', meta: { winner_type: '', confidence: 0, method: '' } },
    })
  })

  it('非预期 JSON（半截 chunk）返回 null 并告警', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(parseSSELine('data: {"type":"text","con')).toBeNull()
    expect(warn).toHaveBeenCalled()
    warn.mockRestore()
  })

  it('普通纯文本按 text 事件输出', () => {
    expect(parseSSELine('data: hello world')).toEqual({
      kind: 'text',
      content: 'hello world',
    })
  })

  it('未知 type 的 JSON 返回 null', () => {
    expect(parseSSELine('data: {"type":"unknown","x":1}')).toBeNull()
  })
})

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((c) => controller.enqueue(encoder.encode(c)))
      controller.close()
    },
  })
  return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

async function collect(chunks: string[], opts?: { sessionId?: string; userId?: string }): Promise<any[]> {
  const fetchMock = vi.fn(async () => sseResponse(chunks))
  vi.stubGlobal('fetch', fetchMock)
  try {
    const events: any[] = []
    for await (const ev of smartChatStream('你好', opts?.sessionId, undefined, opts?.userId)) {
      events.push(ev)
    }
    return events
  } finally {
    vi.unstubAllGlobals()
  }
}

describe('smartChatStream', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('跨 chunk 正确拼装事件（一行被拆成两段）', async () => {
    const events = await collect(['data: {"type":"text","content":"你', '好"}\n\ndata: [DONE]\n\n'])
    expect(events).toEqual([{ type: 'text', content: '你好' }])
  })

  it('多行一次返回按序产出', async () => {
    const body = [
      'data: {"type":"status","stage":"routing","label":"分析意图"}\n\n',
      'data: {"type":"text","content":"回答"}\n\n',
      'data: [DONE]\n\n',
    ]
    const events = await collect(body)
    expect(events).toEqual([
      { type: 'status', stage: 'routing', label: '分析意图' },
      { type: 'text', content: '回答' },
    ])
  })

  it('产出 meta 事件（路由决策透出）', async () => {
    const body = [
      'data: {"type":"meta","meta":{"winner_type":"recommend_workflow","confidence":0.85,"method":"consensus"}}\n\n',
      'data: [DONE]\n\n',
    ]
    const events = await collect(body)
    expect(events).toEqual([
      { type: 'meta', meta: { winner_type: 'recommend_workflow', confidence: 0.85, method: 'consensus' } },
    ])
  })

  it('末尾无换行符时 flush 剩余缓冲', async () => {
    const events = await collect(['data: {"type":"text","content":"末尾"}\n\ndata: [DONE]'])
    expect(events).toEqual([{ type: 'text', content: '末尾' }])
  })

  it('忽略 ping / 非 data 行，非预期 JSON 被跳过', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const body = [
      ': keepalive comment\n\n',
      'event: x\n\n',
      'data: {"type":"text","content":"ok"}\n\n',
      'data: {"type":"text","con\n\n', // 半截 JSON → 跳过
      'data: [DONE]\n\n',
    ]
    const events = await collect(body)
    expect(events).toEqual([{ type: 'text', content: 'ok' }])
    expect(warn).toHaveBeenCalled()
    warn.mockRestore()
  })

  it('纯文本 data 行输出为 text 事件', async () => {
    const events = await collect(['data: plain text\n\ndata: [DONE]\n\n'])
    expect(events).toEqual([{ type: 'text', content: 'plain text' }])
  })

  it('频率限制 429 不重试', async () => {
    const fetchMock = vi.fn(async () => new Response(
      JSON.stringify({ detail: '请求过于频繁，请稍后再试' }),
      { status: 429, headers: { 'Content-Type': 'application/json' } },
    ))
    vi.stubGlobal('fetch', fetchMock)
    await expect(
      (async () => {
        for await (const _ of smartChatStream('hi')) {
          /* noop */
        }
      })()
    ).rejects.toThrow('请求过于频繁')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('401 时抛出异常并派发 auth:unauthorized', async () => {
    const dispatched: string[] = []
    window.addEventListener('auth:unauthorized', () => dispatched.push('unauthorized'))
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 401 })))
    await expect(
      (async () => {
        for await (const _ of smartChatStream('hi')) {
          /* noop */
        }
      })()
    ).rejects.toThrow('HTTP 401')
    expect(dispatched).toContain('unauthorized')
  })
})
