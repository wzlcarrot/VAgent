/**
 * 回归测试：避免"为你找到 N 个相关视频："被误判为视频链接
 * Bug：MessageBubble videoLinks 正则误匹配 winner_text 里的"视频"字
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageBubble from '@/components/chat/MessageBubble.vue'

describe('MessageBubble 视频卡片去重', () => {
  it('有 videos 数组时不应该再渲染 videoLinks（避免正则误匹配 winner_text 里的"视频"）', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '1', role: 'assistant',
          content: '为你找到 2 个相关视频：\n\n**1. 121**\n  推荐理由',
          timestamp: new Date(), status: 'success',
          videos: [
            { videoId: 'v1', title: '121', author: 'tom' },
          ],
        },
      },
    })
    const html = wrapper.html()
    // "相关视频" 误匹配卡片不应该出现（因为已经有 videos 数组了）
    expect(html).not.toContain('点击查看视频')
  })

  it('没有 videos 但文本里有 URL 链接，应该渲染 videoLinks', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '2', role: 'assistant',
          content: '视频链接：[演示视频](https://example.com/v.mp4)',
          timestamp: new Date(), status: 'success',
        },
      },
    })
    const html = wrapper.html()
    expect(html).toContain('点击查看视频')
  })

  it('没有 videos 但「个视频：」不应渲染假相关视频卡片', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '4', role: 'assistant',
          content: '你今天看了 1 个视频：\n- Python 入门到实践：零基础学编程',
          timestamp: new Date(), status: 'success',
        },
      },
    })
    const html = wrapper.html()
    expect(html).not.toContain('点击查看视频')
    expect(html).not.toContain('相关视频')
  })

  it('观看名单有 videos 时保留一句摘要并渲染推荐卡片', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '5', role: 'assistant',
          content: '你今天看了 1 个视频：\n- Python 入门到实践',
          timestamp: new Date(), status: 'success',
          videos: [
            { videoId: 'v1', title: 'Python 入门到实践', author: 'up' },
          ],
          reasons: ['你最近看过'],
        },
      },
    })
    const html = wrapper.html()
    expect(html).toContain('你今天看了 1 个视频')
    expect(html).not.toContain('点击查看视频')
    expect(html).toContain('Python 入门到实践')
    expect(html).not.toContain('推荐 1：')
  })
})
