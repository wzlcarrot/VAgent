/**
 * user store 测试 - 验证登录态持久化策略（token 不入 localStorage）+ 401 清态
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useUserStore } from '@/stores/user'

function makeUser(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    userId: 'u1',
    nickname: '测试用户',
    avatar: '',
    token: 'secret-token-abc',
    tokenExpiresAt: Date.now() / 1000 + 3600,
    fansCount: 1,
    currentCoinCount: 2,
    focusCount: 3,
    ...overrides,
  } as any
}

describe('user store 安全持久化', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('setUser 时 token 不应写入 localStorage（防 XSS 窃取）', () => {
    const store = useUserStore()
    store.setUser(makeUser())
    const stored = JSON.parse(localStorage.getItem('user') || '{}')
    expect(stored.token).toBeUndefined()
    expect(stored.userId).toBe('u1')
  })

  it('内存中保留 token（会话内可用），刷新后为空', () => {
    const store = useUserStore()
    store.setUser(makeUser())
    expect(store.user?.token).toBe('secret-token-abc')

    // 模拟刷新：从 localStorage 恢复（无 token）
    store.user = null
    store.initFromStorage()
    expect(store.user?.token).toBe('')
    expect(store.isLoggedIn).toBe(true)  // 用户信息仍在，鉴权靠 httpOnly cookie
  })

  it('logout 清空内存 + localStorage', () => {
    const store = useUserStore()
    store.setUser(makeUser())
    store.logout()
    expect(store.user).toBeNull()
    expect(store.isLoggedIn).toBe(false)
    expect(localStorage.getItem('user')).toBeNull()
  })

  it('token 过期后 initFromStorage 清除', () => {
    const store = useUserStore()
    // 写入过期的用户信息
    const expired = makeUser({ tokenExpiresAt: Date.now() / 1000 - 10 })
    localStorage.setItem('user', JSON.stringify(expired))
    store.initFromStorage()
    expect(store.user).toBeNull()
    expect(localStorage.getItem('user')).toBeNull()
  })

  it('401 清态后 isLoggedIn 为 false，不会跳转死循环', () => {
    const store = useUserStore()
    store.setUser(makeUser())
    // 模拟 auth:unauthorized 处理流程：logout
    store.logout()
    expect(store.isLoggedIn).toBe(false)
    expect(store.user).toBeNull()
  })
})
