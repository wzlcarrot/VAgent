import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import LoginView from '@/views/LoginView.vue'

describe('LoginView', () => {
  it('不展示测试账密', async () => {
    setActivePinia(createPinia())
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div />' } },
        { path: '/login', component: LoginView },
      ],
    })
    await router.push('/login')
    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })
    expect(wrapper.text()).not.toContain('123456')
    expect(wrapper.text()).not.toContain('test@viewhub.com')
    wrapper.unmount()
  })
})
