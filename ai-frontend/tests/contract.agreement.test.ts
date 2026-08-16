/**
 * 前后端联调契约测试（级别 A）：用后端真实 SSE 输出驱动前端解析器。
 *
 * 后端 tests/test_contract_fixture.py 断言真实 stream 结构符合此契约；
 * 本测试用同一组固定样本验证前端 parseSSELine / smartChatStream 能正确解析，
 * 双向锁死后端产出格式 ↔ 前端消费格式，防止契约断裂（后端改字段/前端漏改）。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { parseSSELine, smartChatStream } from '@/api/chat'

// 从后端真实 stream 抓取的固定样本（greeting 快速路径，不依赖 LLM）
const REAL_BACKEND_SSE = [
  'data: {"type":"status","stage":"routing","label":"分析意图"}',
  '',
  'data: {"type":"status","stage":"parallel","label":"多Agent并行分析"}',
  '',
  'data: {"type":"status","stage":"generating","label":"生成回答"}',
  '',
  'data: {"type":"text","content":"你好！我是你的 AI 智能助手，可以帮你解答问题、推荐视频、查询数据等，有什么可以帮你的吗？"}',
  '',
  'data: {"type":"status","stage":"done","label":"完成"}',
  '',
  'data: [DONE]',
  '',
]

describe('前后端联调契约：后端真实 SSE → 前端 parseSSELine', () => {
  it('status 事件解析出 stage/label（契约字段）', () => {
    const routing = parseSSELine('data: {"type":"status","stage":"routing","label":"分析意图"}')
    expect(routing).toEqual({
      kind: 'event',
      event: { type: 'status', stage: 'routing', label: '分析意图' },
    })
  })

  it('text 事件解析出 content 字符串', () => {
    const ev = parseSSELine('data: {"type":"text","content":"你好"}')
    expect(ev).toEqual({ kind: 'event', event: { type: 'text', content: '你好' } })
  })

  it('[DONE] 解析为终止哨兵', () => {
    expect(parseSSELine('data: [DONE]')).toEqual({ kind: 'done' })
  })

  it('真实后端样本：非 data 空行被忽略', () => {
    expect(parseSSELine('')).toBeNull()
  })

  it('真实后端样本序列可被 smartChatStream 完整消费', async () => {
    const encoder = new TextEncoder()
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        REAL_BACKEND_SSE.forEach((chunk) => controller.enqueue(encoder.encode(chunk + '\n')))
        controller.close()
      },
    })
    const fetchMock = vi.fn(async () => new Response(stream, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const events: any[] = []
    for await (const ev of smartChatStream('你好')) {
      events.push(ev)
    }
    vi.unstubAllGlobals()

    // 契约：routing → parallel → generating → text → done，无 videos（greeting 路径）
    const types = events.map((e) => e.type)
    expect(types).toEqual(['status', 'status', 'status', 'text', 'status'])
    const statuses = events.filter((e) => e.type === 'status').map((e) => e.stage)
    expect(statuses).toEqual(['routing', 'parallel', 'generating', 'done'])
    // text 事件 content 为字符串
    const textEv = events.find((e) => e.type === 'text')
    expect(typeof textEv.content).toBe('string')
    expect(textEv.content).toContain('AI 智能助手')
  })
})
