/**
 * 回归测试：连续发送消息 ChatInput 不卡死
 * Bug 修复验证：isSending 必须能被重置
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import ChatInput from '@/components/chat/ChatInput.vue'

describe('ChatInput 连续发送不卡死（回归）', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('isSending 500ms 后应该被自动重置（防止父组件忘记 setReady）', async () => {
    const wrapper = mount(ChatInput)
    const textarea = wrapper.find('textarea')

    await textarea.setValue('第一条消息')
    await wrapper.find('.send-btn').trigger('click')

    // 立即检查：isSending 应该是 true
    expect((wrapper.vm as any).isSending).toBe(true)

    // 500ms 后：应该被自动重置
    vi.advanceTimersByTime(500)
    await nextTick()
    expect((wrapper.vm as any).isSending).toBe(false)
  })

  it('isStreaming=true 时按钮应该 disable', async () => {
    const wrapper = mount(ChatInput, {
      props: { isStreaming: true },
    })
    await wrapper.find('textarea').setValue('内容')
    const btn = wrapper.find('.send-btn')
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('isStreaming=false 且有内容时按钮可点击', async () => {
    const wrapper = mount(ChatInput, {
      props: { isStreaming: false },
    })
    await wrapper.find('textarea').setValue('内容')
    const btn = wrapper.find('.send-btn')
    expect((btn.element as HTMLButtonElement).disabled).toBe(false)
  })

  it('isStreaming=false 但无内容时按钮应该 disable', async () => {
    const wrapper = mount(ChatInput, {
      props: { isStreaming: false },
    })
    // 不输入任何内容
    const btn = wrapper.find('.send-btn')
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('连续发 3 条消息都不卡死', async () => {
    const wrapper = mount(ChatInput)
    const textarea = wrapper.find('textarea')

    for (let i = 1; i <= 3; i++) {
      await textarea.setValue(`消息 ${i}`)
      await wrapper.find('.send-btn').trigger('click')

      // 500ms 后 isSending 重置
      vi.advanceTimersByTime(500)
      await nextTick()

      // 此时按钮应该可点击（除非没内容）
      await textarea.setValue('')  // 清空模拟接收
      const btn = wrapper.find('.send-btn')
      expect((btn.element as HTMLButtonElement).disabled).toBe(true)  // 空内容时 disabled

      await textarea.setValue(`消息 ${i + 1} 准备中`)
      expect((btn.element as HTMLButtonElement).disabled).toBe(false)
    }
  })

  it('发送后 previewUrls 应该是空数组（不是空字符串）', async () => {
    const wrapper = mount(ChatInput)
    // 直接设置一个 URL
    ;(wrapper.vm as any).previewUrls.push('data:image/png;base64,xyz')
    expect((wrapper.vm as any).previewUrls.length).toBe(1)

    // 触发发送
    await wrapper.find('textarea').setValue('带图消息')
    await wrapper.find('.send-btn').trigger('click')

    // previewUrls 应该被清空为 []
    expect((wrapper.vm as any).previewUrls).toEqual([])
  })
})
