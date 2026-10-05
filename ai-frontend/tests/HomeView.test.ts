import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import HomeView from '@/views/HomeView.vue'
import { useUserStore } from '@/stores/user'
import { getChatHistory } from '@/api/chat'

vi.mock('@/api/chat', () => ({
  getChatHistory: vi.fn().mockResolvedValue([]),
  sendChatStream: vi.fn(),
  smartChatStream: vi.fn(),
  submitApproval: vi.fn(),
  stopChat: vi.fn(),
  trackRecommendClick: vi.fn(),
}))

function loginDemoUser() {
  const userStore = useUserStore()
  userStore.setUser({
    userId: 'demo_user',
    nickname: '演示用户',
    avatar: '',
    token: '',
    tokenExpiresAt: Math.floor(Date.now() / 1000) + 3600,
    fansCount: 0,
    currentCoinCount: 0,
    focusCount: 0,
  })
}

async function mountHome(query: Record<string, string> = {}) {
  setActivePinia(createPinia())
  loginDemoUser()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: HomeView }],
  })
  await router.push({ path: '/', query })
  await router.isReady()
  return mount(HomeView, {
    global: {
      plugins: [router],
      stubs: {
        AppHeader: true,
        AppSidebar: true,
        ChatInput: true,
        MessageBubble: true,
        WorkflowIndicator: true,
        HarnessDebugPanel: true,
        ToolProgressBar: true,
        QuickActions: true,
        VideoCard: true,
        ConfirmDialog: true,
      },
    },
  })
}

describe('HomeView', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('带入 ?video= 时提示当前视频上下文', async () => {
    const wrapper = await mountHome({ video: 'demo01' })
    await flushPromises()
    expect(wrapper.text()).toContain('当前视频上下文已就绪')
    wrapper.unmount()
  })

  it('无 video 时走通用欢迎文案', async () => {
    const wrapper = await mountHome()
    await flushPromises()
    expect(wrapper.text()).toContain('推荐视频')
    wrapper.unmount()
  })

  it('带 sessionId 时拉取历史', async () => {
    vi.mocked(getChatHistory).mockResolvedValueOnce([])
    const wrapper = await mountHome({ session: 'sess-1' })
    await flushPromises()
    expect(getChatHistory).toHaveBeenCalled()
    wrapper.unmount()
  })
})
