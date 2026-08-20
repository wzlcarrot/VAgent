/**
 * WorkflowIndicator 组件测试 - stage 状态机映射
 */
import { describe, it, expect, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import WorkflowIndicator from '@/components/chat/WorkflowIndicator.vue'

describe('WorkflowIndicator', () => {
  let wrapper: ReturnType<typeof mount>

  afterEach(() => {
    wrapper?.unmount()
  })

  function mountVisible(stage = '', label = '') {
    wrapper = mount(WorkflowIndicator, {
      props: { visible: true, stage, label },
    })
    return wrapper
  }

  it('visible=true 时渲染 3 个步骤，初始 pending', () => {
    wrapper = mountVisible()
    const steps = wrapper.findAll('.step')
    expect(steps).toHaveLength(3)
    expect(wrapper.find('.step.pending').exists()).toBe(true)
    expect(wrapper.text()).toContain('分析意图')
    expect(wrapper.text()).toContain('检索知识')
    expect(wrapper.text()).toContain('生成回复')
  })

  it('visible=false 时不渲染', () => {
    wrapper = mount(WorkflowIndicator, { props: { visible: false, stage: '', label: '' } })
    expect(wrapper.find('.workflow-indicator').exists()).toBe(false)
  })

  it('stage=routing 时该步骤 active 并显示当前步骤', async () => {
    wrapper = mountVisible()
    await wrapper.setProps({ stage: 'routing' })
    await nextTick()
    expect(wrapper.find('.step.active').text()).toContain('分析意图')
    expect(wrapper.text()).toContain('当前: 分析意图')
  })

  it('stage=retrieval 时 routing 完成、retrieval active', async () => {
    wrapper = mountVisible()
    await wrapper.setProps({ stage: 'retrieval' })
    await nextTick()
    const texts = wrapper.findAll('.step').map(s => s.classes())
    expect(texts[0]).toContain('completed')
    expect(texts[1]).toContain('active')
    expect(wrapper.text()).toContain('当前: 检索知识')
  })

  it('stage=done 时全部 completed 并显示"完成"', async () => {
    wrapper = mountVisible()
    await wrapper.setProps({ stage: 'done' })
    await nextTick()
    const texts = wrapper.findAll('.step').map(s => s.classes())
    expect(texts.every(c => c.includes('completed'))).toBe(true)
    expect(wrapper.text()).toContain('当前: 完成')
  })

  it('优先使用传入 label 作为当前步骤名', async () => {
    wrapper = mountVisible()
    await wrapper.setProps({ stage: 'generating', label: '正在生成答案' })
    await nextTick()
    expect(wrapper.text()).toContain('当前: 正在生成答案')
  })

  it('有 route 时展示路由决策（意图·方法·置信度）', () => {
    wrapper = mount(WorkflowIndicator, {
      props: {
        visible: true,
        stage: 'generating',
        label: '生成回复',
        route: { winner_type: 'recommend_workflow', confidence: 0.85, method: 'consensus' },
      },
    })
    const text = wrapper.text()
    expect(text).toContain('路由')
    expect(text).toContain('视频推荐')
    expect(text).toContain('关键词+语义一致')
    expect(text).toContain('置信度 85%')
  })

  it('route 为空时渲染路由决策', () => {
    wrapper = mountVisible()
    expect(wrapper.find('.route-decision').exists()).toBe(false)
  })
})
