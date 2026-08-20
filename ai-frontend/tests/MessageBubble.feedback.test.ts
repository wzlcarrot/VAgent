import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageBubble from '@/components/chat/MessageBubble.vue'

vi.mock('@/api/chat', () => ({
  submitFeedback: vi.fn().mockResolvedValue({ success: true }),
}))

describe('MessageBubble 反馈', () => {
  it('助手成功消息带 sessionId 时提交 video_ids', async () => {
    const { submitFeedback } = await import('@/api/chat')
    const wrapper = mount(MessageBubble, {
      props: {
        sessionId: 's1',
        messageIndex: 2,
        message: {
          id: 'f1',
          role: 'assistant',
          content: '推荐',
          timestamp: new Date(),
          status: 'success',
          videos: [{ videoId: 'v1', title: '甲' }],
        },
      },
    })
    await wrapper.get('[aria-label="没用"]').trigger('click')
    expect(submitFeedback).toHaveBeenCalledWith({
      session_id: 's1',
      message_index: 2,
      feedback: 'not_helpful',
      video_ids: ['v1'],
    })
  })
})
