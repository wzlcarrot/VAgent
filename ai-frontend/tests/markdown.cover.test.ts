import { describe, it, expect } from 'vitest'
import { renderMarkdown } from '@/utils/markdown'

describe('renderMarkdown 推荐封面', () => {
  it('应保留带 query 的同源封面图', () => {
    const md = '![封面](</ai/media/cover?sourceName=cover/a.jpg>)'
    const html = renderMarkdown(md)
    expect(html).toContain('<img')
    expect(html).toContain('/ai/media/cover?sourceName=cover/a.jpg')
    expect(html).not.toContain('onerror')
  })

  it('应把旧的 getResource 封面地址改写为同源代理', () => {
    const md = '![封面](http://gateway:8080/api/file/getResource?sourceName=cover/a.jpg)'
    const html = renderMarkdown(md)
    expect(html).toContain('<img')
    expect(html).toContain('/ai/media/cover?sourceName=cover/a.jpg')
    expect(html).not.toContain('gateway')
  })

  it('代码块按声明语言高亮', () => {
    const html = renderMarkdown('```js\nconst a = 1\n```')
    expect(html).toContain('hljs')
    expect(html).toContain('const')
  })

  it('无语言代码块走转义兜底', () => {
    const html = renderMarkdown('```\n<b>hi</b>\n```')
    expect(html).toContain('hljs')
  })

  it('无 sourceName 的图片地址保持原样', () => {
    const html = renderMarkdown('![x](https://cdn.example.com/a.png)')
    expect(html).toContain('https://cdn.example.com/a.png')
  })
})
