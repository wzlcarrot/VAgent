/**
 * Citations 刷新 smoke：流式收到 citations → 刷新后从历史 API 恢复展示。
 *
 *   cd ai-frontend && npm run test:e2e          # 全 mock，CI 可跑
 *   E2E_LIVE=1 npm run test:e2e                 # 真实登录 + mock SSE/history
 */
import { test, expect, type Page } from '@playwright/test'

const TEST_EMAIL = 'test@viewhub.com'
const TEST_PASSWORD = '123456'
const MOCK_SNIPPET = 'Python 入门语法与变量定义'

function sseBody(events: object[]): string {
  return events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('') + 'data: [DONE]\n\n'
}

const MOCK_STREAM = sseBody([
  { type: 'status', stage: 'routing', label: '分析意图' },
  { type: 'status', stage: 'parallel', label: '主流程与兜底并行执行' },
  {
    type: 'meta',
    meta: { winner_type: 'video_qa_workflow', confidence: 0.85, method: 'consensus' },
  },
  {
    type: 'citations',
    citations: [{ id: 1, snippet: MOCK_SNIPPET, score: 0.91, video_id: 'v_e2e' }],
  },
  { type: 'text', content: `本视频讲解 ${MOCK_SNIPPET}[1]。` },
  { type: 'status', stage: 'done', label: '完成' },
])

function mockStreamRoute(page: Page) {
  return page.route('**/ai/chat/stream', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
      body: MOCK_STREAM,
    })
  })
}

function mockEmptyAuthRoutes(page: Page) {
  return Promise.all([
    page.route('**/ai/chat/sessions**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: '{"sessions":[]}',
      })
    }),
    page.route('**/ai/chat/history**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: '{"messages":[]}',
      })
    }),
  ])
}

function mockHistoryRoute(page: Page, sessionId: string) {
  return page.route('**/ai/chat/history**', async (route) => {
    const url = route.request().url()
    if (!url.includes('session_id=')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"messages":[]}' })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        messages: [
          {
            role: 'user',
            content: '这个视频讲了什么',
            timestamp: '2026-01-01T00:00:00Z',
            session_id: sessionId,
          },
          {
            role: 'assistant',
            content: `本视频讲解 ${MOCK_SNIPPET}[1]。`,
            timestamp: '2026-01-01T00:00:01Z',
            session_id: sessionId,
            citations: [{ id: 1, snippet: MOCK_SNIPPET, score: 0.91, video_id: 'v_e2e' }],
          },
        ],
      }),
    })
  })
}

async function backendHealthy(): Promise<boolean> {
  try {
    const res = await fetch('http://127.0.0.1:9090/health', { signal: AbortSignal.timeout(2000) })
    return res.ok
  } catch {
    return false
  }
}

async function seedOfflineUser(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem(
      'user',
      JSON.stringify({
        userId: 'test_user_001',
        nickname: '测试用户',
        avatar: '',
        tokenExpiresAt: Math.floor(Date.now() / 1000) + 86400,
        fansCount: 0,
        currentCoinCount: 128,
        focusCount: 0,
      }),
    )
  })
}

async function loginViaUi(page: Page) {
  await page.goto('/login')
  await page.locator('input[type="email"]').fill(TEST_EMAIL)
  await page.locator('input[type="password"]').fill(TEST_PASSWORD)
  await page.locator('button.btn-login').click()
  await page.waitForURL('/', { timeout: 15_000 })
}

async function readSessionId(page: Page): Promise<string> {
  const sid = await page.evaluate(() => {
    const raw = localStorage.getItem('viewhub_sessions')
    if (!raw) return ''
    const sessions = JSON.parse(raw) as Array<{ id: string }>
    return sessions[0]?.id || ''
  })
  expect(sid).toBeTruthy()
  return sid
}

async function sendQuestion(page: Page, text: string) {
  const input = page.locator('textarea.chat-input')
  await input.fill(text)
  await expect(page.locator('button.send-btn')).toBeEnabled({ timeout: 10_000 })
  await input.press('Enter')
}

test.describe('Citations 刷新 smoke', () => {
  test('流式 citations 展示并在刷新后保留', async ({ page }) => {
    const live = process.env.E2E_LIVE === '1' && (await backendHealthy())

    await mockStreamRoute(page)

    if (live) {
      await loginViaUi(page)
    } else {
      await mockEmptyAuthRoutes(page)
      await seedOfflineUser(page)
      await page.goto('/')
    }

    await expect(page.locator('textarea.chat-input')).toBeVisible()
    await page.goto('/?video=v_e2e')
    await expect(page.locator('textarea.chat-input')).toBeVisible()

    await sendQuestion(page, '这个视频讲了什么')

    const citations = page.locator('[data-testid="citations-block"]')
    await expect(citations).toBeVisible({ timeout: 30_000 })
    await expect(citations.locator('.citation-snippet')).toContainText(MOCK_SNIPPET)

    const sessionId = await readSessionId(page)
    await mockHistoryRoute(page, sessionId)

    await page.reload()
    await expect(page.locator('[data-testid="citations-block"]')).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('.citation-snippet')).toContainText(MOCK_SNIPPET)
  })
})
