/**
 * XSS 注入测试 - 验证 MessageBubble.vue + DOMPurify 防 XSS
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageBubble from '@/components/chat/MessageBubble.vue'

describe('MessageBubble XSS 防护', () => {
  it('应该过滤 <script> 标签', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '1',
          role: 'assistant',
          content: '<script>alert("XSS")</script>正常文本',
          timestamp: new Date(),
          status: 'success',
        },
      },
    })
    const html = wrapper.html()
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('alert')
  })

  it('应该过滤 <img onerror> 攻击载荷', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '2',
          role: 'assistant',
          content: '<img src=x onerror="alert(1)">',
          timestamp: new Date(),
          status: 'success',
        },
      },
    })
    const html = wrapper.html()
    expect(html).not.toContain('onerror')
    expect(html).not.toContain('alert')
  })

  it('应该过滤 <svg onload> 攻击载荷', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '3',
          role: 'assistant',
          content: '<svg onload="alert(1)"></svg>',
          timestamp: new Date(),
          status: 'success',
        },
      },
    })
    const html = wrapper.html()
    expect(html).not.toContain('onload')
    expect(html).not.toContain('alert')
  })

  it('应该过滤 javascript: URL', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '4',
          role: 'assistant',
          content: '<a href="javascript:alert(1)">点我</a>',
          timestamp: new Date(),
          status: 'success',
        },
      },
    })
    const html = wrapper.html()
    // javascript: URL 应该被剥离或中和
    expect(html).not.toMatch(/href="javascript:/i)
  })

  it('应该过滤 iframe 注入', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '5',
          role: 'assistant',
          content: '<iframe src="https://evil.com"></iframe>正常',
          timestamp: new Date(),
          status: 'success',
        },
      },
    })
    const html = wrapper.html()
    expect(html).not.toContain('<iframe')
  })

  it('应该过滤 MiniMax-M3 的 <think> 块', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '6',
          role: 'assistant',
          content: '<think>这是推理过程</think>实际回答',
          timestamp: new Date(),
          status: 'success',
        },
      },
    })
    const html = wrapper.html()
    expect(html).not.toContain('<think>')
    expect(html).not.toContain('这是推理过程')
    expect(html).toContain('实际回答')
  })

  it('应该正确渲染 Markdown', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '7',
          role: 'assistant',
          content: '# 标题\n\n**粗体** *斜体*',
          timestamp: new Date(),
          status: 'success',
        },
      },
    })
    const html = wrapper.html()
    expect(html).toContain('标题')
    expect(html).toContain('粗体')
  })

  it('应该保留视频链接 [标题](url.mp4) 转成 <a>', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '8',
          role: 'assistant',
          content: '[视频](https://example.com/clip.mp4)',
          timestamp: new Date(),
          status: 'success',
        },
      },
    })
    const html = wrapper.html()
    expect(html).toContain('<a')
    expect(html).toContain('video-link')
  })

  it('应该正确格式化时间（今天显示时分）', () => {
    const now = new Date()
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '9',
          role: 'assistant',
          content: '内容',
          timestamp: now,
          status: 'success',
        },
      },
    })
    const text = wrapper.text()
    expect(text).toMatch(/\d{1,2}:\d{2}/)
  })

  it('应该正确格式化时间（非今天显示日期）', () => {
    const old = new Date('2020-01-01')
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '10',
          role: 'assistant',
          content: '内容',
          timestamp: old,
          status: 'success',
        },
      },
    })
    const text = wrapper.text()
    expect(text).toMatch(/2020|01\/01/)
  })

  it('应该处理空 content', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '11',
          role: 'assistant',
          content: '',
          timestamp: new Date(),
          status: 'success',
        },
      },
    })
    expect(wrapper.exists()).toBe(true)
  })

  it('应该处理极长 content', () => {
    const longContent = 'A'.repeat(100000)
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '12',
          role: 'assistant',
          content: longContent,
          timestamp: new Date(),
          status: 'success',
        },
      },
    })
    expect(wrapper.exists()).toBe(true)
  })

  it('应该区分 user 和 assistant 角色样式', () => {
    const userWrapper = mount(MessageBubble, {
      props: {
        message: {
          id: 'u1', role: 'user', content: 'user',
          timestamp: new Date(), status: 'success',
        },
      },
    })
    const aiWrapper = mount(MessageBubble, {
      props: {
        message: {
          id: 'a1', role: 'assistant', content: 'ai',
          timestamp: new Date(), status: 'success',
        },
      },
    })
    expect(userWrapper.classes()).not.toEqual(aiWrapper.classes())
  })

  it('error 状态应该显示错误标识', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: {
          id: '13', role: 'assistant', content: '出错了',
          timestamp: new Date(), status: 'error',
        },
      },
    })
    const html = wrapper.html()
    expect(html).toMatch(/error|失败|重试/i)
  })
})