import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import HistoryView from '@/views/HistoryView.vue'

vi.mock('@/api/chat', () => ({
  getChatSessions: vi.fn().mockResolvedValue([]),
  getChatHistory: vi.fn().mockResolvedValue([]),
  deleteChatSession: vi.fn(),
  searchChatContent: vi.fn().mockResolvedValue([]),
}))

describe('HistoryView', () => {
  it('空列表展示空状态文案', async () => {
    setActivePinia(createPinia())
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/history', component: HistoryView }],
    })
    await router.push('/history')
    const wrapper = mount(HistoryView, {
      global: {
        plugins: [router],
        stubs: { AppHeader: true },
      },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('暂无历史对话')
    wrapper.unmount()
  })
})
