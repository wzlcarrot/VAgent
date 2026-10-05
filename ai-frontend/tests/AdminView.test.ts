import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import AdminView from '@/views/AdminView.vue'

vi.mock('@/api/admin', () => ({
  fetchBusinessQuality: vi.fn().mockResolvedValue({}),
  fetchAdminFeatures: vi.fn().mockResolvedValue({ web_search_enabled: true }),
  fetchCompactStats: vi.fn().mockResolvedValue({}),
  fetchIndexStats: vi.fn().mockResolvedValue({}),
  fetchLlmCircuit: vi.fn().mockResolvedValue({}),
  fetchSessionRuns: vi.fn().mockResolvedValue({ runs: [] }),
  fetchStreamPermits: vi.fn().mockResolvedValue({}),
  fetchTraceSessions: vi.fn().mockResolvedValue({ sessions: [] }),
  fetchTraceSummary: vi.fn().mockResolvedValue({}),
  fetchWeeklyGolden: vi.fn().mockResolvedValue({ items: [] }),
  indexVideo: vi.fn(),
  registerLocalVideo: vi.fn(),
  reindexPendingVideos: vi.fn(),
}))

describe('AdminView', () => {
  it('展示运维控制台标题', async () => {
    sessionStorage.setItem('vagent_admin_key', 'k')
    setActivePinia(createPinia())
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/admin', component: AdminView }],
    })
    await router.push('/admin')
    const wrapper = mount(AdminView, {
      global: {
        plugins: [router],
        stubs: { AppHeader: true },
      },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('运维控制台')
    wrapper.unmount()
  })
})
