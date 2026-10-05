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

  it('有 videos 时隐藏正文 Markdown（卡片自己展示标题封面）', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '4', role: 'assistant',
          content: '**推荐 1：机器学习入门**\n\n关键词：AI\n播放量：40次',
          timestamp: new Date(), status: 'success',
          videos: [{ videoId: 'v1', title: '机器学习入门' }],
        },
      },
    })
    expect(wrapper.html()).not.toContain('关键词')
    expect(wrapper.html()).not.toContain('播放量')
  })

  it('没有 videos 时，文本应该正常显示', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '3', role: 'assistant',
          content: '为你推荐以下视频请明确告诉我你的偏好',
          timestamp: new Date(), status: 'success',
        },
      },
    })
    const html = wrapper.html()
    expect(html.length).toBeGreaterThan(0)
  })
})
