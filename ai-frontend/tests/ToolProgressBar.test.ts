import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ToolProgressBar from '@/components/chat/ToolProgressBar.vue'
import type { ToolBlock } from '@/composables/useToolProgress'

describe('ToolProgressBar', () => {
  it('renders nothing when tools empty', () => {
    const w = mount(ToolProgressBar, { props: { tools: [] } })
    expect(w.find('.tool-progress-bar').exists()).toBe(false)
  })

  it('renders running / done(with duration) / failed', () => {
    const tools: ToolBlock[] = [
      { name: 'a', label: '检索', status: 'running' },
      { name: 'b', label: '回答', status: 'done', durationMs: 12 },
      { name: 'c', label: '失败项', status: 'failed' },
    ]
    const w = mount(ToolProgressBar, { props: { tools } })
    expect(w.findAll('.tool-item')).toHaveLength(3)
    expect(w.text()).toContain('执行中')
    expect(w.text()).toContain('完成')
    expect(w.text()).toContain('12ms')
    expect(w.text()).toContain('失败')
    expect(w.find('.tool-item.running').exists()).toBe(true)
    expect(w.find('.tool-item.failed').exists()).toBe(true)
  })
})
