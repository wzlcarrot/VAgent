/**
 * 前后端真实联调测试（级别 B）：前端 smartChatStream 直接消费真后端 SSE 流。
 *
 * 前置条件：后端已在 127.0.0.1:18080 运行，且 test 账户可用。
 * 通过 mock @/config/api 把 interviewMode 指向真实后端。
 * 不纳入默认 `vitest run`（避免 CI 依赖真实后端），单独触发：
 *   npx vitest run tests/e2e.integration.test.ts
 */
import { describe, it, expect, afterEach } from 'vitest'
import { smartChatStream } from '@/api/chat'

const API = 'http://127.0.0.1:18080'

// 指向真实后端：让 getStreamUrl 返回完整后端地址（interviewMode 直连）
vi.mock('@/config/api', () => ({
  interviewMode: { enabled: true, pythonApi: 'http://127.0.0.1:18080' },
  http: {
    get: () => Promise.reject(new Error('http 未在此集成测试中使用')),
  },
}))

async function realLogin(): Promise<string> {
  const res = await fetch(`${API}/ai/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'test@viewhub.com', password: '123456' }),
  })
  const data = await res.json()
  return data.user?.token
}

describe('前后端真实联调（需要后端运行在 :18080）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('登录并消费真实 SSE 流（真实后端字节 → 前端解析器）', async () => {
    const token = await realLogin()
    expect(typeof token).toBe('string')
    expect(token.length).toBeGreaterThan(0)

    const events: any[] = []
    for await (const ev of smartChatStream('你好', undefined, undefined, undefined, token)) {
      events.push(ev)
    }

    // 契约：status 阶段序列 + text + 结束
    const types = events.map((e) => e.type)
    expect(types).toContain('status')
    expect(types).toContain('text')

    // status 阶段以 done 收尾
    const stages = events.filter((e) => e.type === 'status').map((e) => e.stage)
    expect(stages).toContain('routing')
    expect(stages[stages.length - 1]).toBe('done')

    // text 事件 content 非空字符串
    const textEv = events.find((e) => e.type === 'text')
    expect(typeof textEv?.content).toBe('string')
    expect((textEv?.content || '').length).toBeGreaterThan(0)
  }, 30000)
})
