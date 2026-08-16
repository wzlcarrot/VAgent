/**
 * QuickActions 组件测试 - 快捷操作按钮的展示与 select 事件
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import QuickActions from '@/components/chat/QuickActions.vue'

describe('QuickActions', () => {
  it('默认渲染 3 个快捷操作按钮', () => {
    const wrapper = mount(QuickActions)
    const btns = wrapper.findAll('.action-btn')
    expect(btns).toHaveLength(3)
    expect(wrapper.text()).toContain('视频推荐')
    expect(wrapper.text()).toContain('网站介绍')
    expect(wrapper.text()).toContain('使用帮助')
  })

  it('点击"视频推荐"触发 select 事件且 payload 正确', async () => {
    const wrapper = mount(QuickActions)
    const btn = wrapper.findAll('.action-btn')[0]
    await btn.trigger('click')
    expect(wrapper.emitted('select')).toBeTruthy()
    expect(wrapper.emitted('select')![0][0]).toBe('推荐一些适合我的视频')
  })

  it('点击"使用帮助"触发对应 payload', async () => {
    const wrapper = mount(QuickActions)
    const btn = wrapper.findAll('.action-btn')[2]
    await btn.trigger('click')
    expect(wrapper.emitted('select')![0][0]).toBe('这个平台怎么使用？')
  })

  it('visible=false 时不渲染', () => {
    const wrapper = mount(QuickActions, { props: { visible: false } })
    expect(wrapper.find('.quick-actions').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('快捷操作')
  })

  it('visible 默认值为 true', () => {
    const wrapper = mount(QuickActions)
    expect(wrapper.find('.quick-actions').exists()).toBe(true)
  })
})
