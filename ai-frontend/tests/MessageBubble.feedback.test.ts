import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageBubble from '@/components/chat/MessageBubble.vue'

vi.mock('@/api/chat', () => ({
  submitFeedback: vi.fn().mockResolvedValue({ success: true, suggest_rebatch: true }),
}))

describe('MessageBubble 反馈', () => {
  it('点没用先选原因再提交，并可换一批', async () => {
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
    expect(wrapper.find('[data-testid="feedback-reasons"]').exists()).toBe(true)
    expect(submitFeedback).not.toHaveBeenCalled()

    await wrapper.get('.reason-chip').trigger('click')
    expect(submitFeedback).toHaveBeenCalledWith({
      session_id: 's1',
      message_index: 2,
      feedback: 'not_helpful',
      video_ids: ['v1'],
      question: '',
      answer: '推荐',
      reason: 'off_topic',
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.rebatch-btn').exists()).toBe(true)
    await wrapper.get('.rebatch-btn').trigger('click')
    expect(wrapper.emitted('rebatch')).toBeTruthy()
  })
})
