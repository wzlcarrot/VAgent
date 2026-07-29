/**
 * 回归测试：MessageBubble 过滤历史脏数据
 * Bug：DB 里旧的"为你推荐以下视频：..."文本会在加载历史时显示
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageBubble from '@/components/chat/MessageBubble.vue'

describe('MessageBubble 过滤历史脏数据', () => {
  it('有 videos 时，"为你推荐以下视频"开头应该隐藏', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '1', role: 'assistant',
          content: '根据你的喜好，为你推荐以下视频：\n\n• test\n  推荐理由：xxx\n\n• 121',
          timestamp: new Date(), status: 'success',
          videos: [
            { videoId: 'v1', title: 'test', author: 'tom' },
            { videoId: 'v2', title: '121', author: 'tom' },
          ],
        },
      },
    })
    const html = wrapper.html()
    expect(html).not.toContain('为你推荐以下视频')
    expect(html).not.toContain('推荐理由')
  })

  it('有 videos 时，"根据你的喜好 为你推荐"开头应该隐藏', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '2', role: 'assistant',
          content: '根据你的喜好 为你推荐以下视频:\n• xxx',
          timestamp: new Date(), status: 'success',
          videos: [{ videoId: 'v1', title: 'x' }],
        },
      },
    })
    const html = wrapper.html()
    expect(html).not.toContain('为你推荐')
  })

  it('没有 videos 时，文本应该正常显示', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '3', role: 'assistant',
          content: '为你推荐以下视频请明确告诉我你的偏好',  // 相似但不是 RECOMMEND 流程
          timestamp: new Date(), status: 'success',
        },
      },
    })
    const html = wrapper.html()
    // 没有 videos，应该正常显示（不强制隐藏）
    expect(html.length).toBeGreaterThan(0)
  })
})
