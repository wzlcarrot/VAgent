/**
 * chat store 测试 - 验证 localStorage 去抖写入
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '@/stores/chat'

describe('chat store localStorage 去抖', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('连续 updateMessage 应合并为一次写入', async () => {
    const store = useChatStore()
    const session = store.createSession()
    const msg = store.addMessage({ role: 'user', content: 'hi', status: 'success' })

    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')

    // 模拟流式输出：连续 100 次 updateMessage
    for (let i = 0; i < 100; i++) {
      store.updateMessage(msg.id, { content: 'hi' + 'a'.repeat(i), status: 'sending' })
    }

    // 300ms 内不应该写入（debounce）
    expect(setItemSpy).not.toHaveBeenCalled()

    // 等待 debounce 触发
    await new Promise(resolve => setTimeout(resolve, 350))

    // debounce 后只应该调用 1 次
    expect(setItemSpy).toHaveBeenCalledTimes(1)
  })

  it('finalizeStreaming 应该立即写入', async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')
    const store = useChatStore()
    store.createSession()
    const msg = store.addMessage({ role: 'user', content: 'hi', status: 'success' })

    setItemSpy.mockClear()  // 清除前面 setup 阶段的写入
    store.updateMessage(msg.id, { content: 'streaming', status: 'sending' })

    expect(setItemSpy).not.toHaveBeenCalled()
    store.finalizeStreaming()
    expect(setItemSpy).toHaveBeenCalled()
  })

  it('createSession 应该立即写入（不 debounce）', () => {
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')
    const store = useChatStore()
    setItemSpy.mockClear()
    store.createSession()
    expect(setItemSpy).toHaveBeenCalled()
  })

  it('addMessage 触发 schedulePersist', async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')
    const store = useChatStore()
    store.createSession()
    setItemSpy.mockClear()

    store.addMessage({ role: 'user', content: 'msg', status: 'success' })

    expect(setItemSpy).not.toHaveBeenCalled()
    await new Promise(resolve => setTimeout(resolve, 350))
    expect(setItemSpy).toHaveBeenCalled()
  })

  it('deleteSession 应该立即写入', () => {
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')
    const store = useChatStore()
    const session = store.createSession()
    setItemSpy.mockClear()

    store.deleteSession(session.id)
    expect(setItemSpy).toHaveBeenCalled()
  })

  it('localStorage 满时不应抛异常', () => {
    const store = useChatStore()
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceeded')
    })
    expect(() => store.createSession()).not.toThrow()
  })

  it('reset 应清空全部会话状态与 localStorage', () => {
    const store = useChatStore()
    const session = store.createSession()
    store.addMessage({ role: 'user', content: 'hi', status: 'success' })
    expect(store.sessions.length).toBe(1)
    expect(store.messages.length).toBe(1)
    expect(localStorage.getItem('viewhub_sessions')).toBeTruthy()

    store.reset()

    expect(store.sessions.length).toBe(0)
    expect(store.messages.length).toBe(0)
    expect(store.currentSessionId).toBeNull()
    expect(localStorage.getItem('viewhub_sessions')).toBeNull()
  })
})