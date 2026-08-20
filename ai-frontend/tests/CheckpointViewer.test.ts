/**
 * CheckpointViewer 组件测试 - 加载、空态、错误、数据展示
 * 用 mock 替代 getCheckpoints API，验证状态流转。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import CheckpointViewer from '@/components/chat/CheckpointViewer.vue'

const attachTo = typeof document !== 'undefined' ? document.body : undefined

// Mock API 模块
vi.mock('@/api/chat', () => ({
  getCheckpoints: vi.fn(),
  resumeWorkflow: vi.fn(),
}))

import { getCheckpoints, resumeWorkflow } from '@/api/chat'

const mockGet = getCheckpoints as unknown as ReturnType<typeof vi.fn>
const mockResume = resumeWorkflow as unknown as ReturnType<typeof vi.fn>

const cpData = {
  checkpoints: [
    {
      workflow_type: 'recommend',
      last_completed_step: 'summary_node',
      steps: [
        { step_name: 'profile_node', status: 'completed', created_at: '2026-08-01T10:00:00' },
        { step_name: 'summary_node', status: 'completed', created_at: '2026-08-01T10:00:01' },
      ],
    },
  ],
}

describe('CheckpointViewer', () => {
  let wrapper: ReturnType<typeof mount>

  afterEach(() => {
    wrapper?.unmount()
    document.body.innerHTML = ''
    vi.clearAllMocks()
  })

  it('visible=false 时不渲染', async () => {
    wrapper = mount(CheckpointViewer, { props: { visible: false, sessionId: 's1' }, attachTo })
    await nextTick()
    expect(document.querySelector('.checkpoint-modal')).toBeNull()
  })

  it('加载中显示 loading 态', async () => {
    mockGet.mockImplementation(() => new Promise(() => {})) // 挂起
    wrapper = mount(CheckpointViewer, { props: { visible: true, sessionId: 's1' }, attachTo })
    await nextTick()
    expect(document.body.textContent).toContain('加载中')
    expect(mockGet).toHaveBeenCalledWith('s1')
  })

  it('无数据时显示空态', async () => {
    mockGet.mockResolvedValue({ checkpoints: [] })
    wrapper = mount(CheckpointViewer, { props: { visible: true, sessionId: 's1' }, attachTo })
    await flushPromises()
    expect(document.body.textContent).toContain('暂无 checkpoint')
  })

  it('接口报错时显示错误信息', async () => {
    mockGet.mockRejectedValue({ response: { data: { detail: '会话不存在' } } })
    wrapper = mount(CheckpointViewer, { props: { visible: true, sessionId: 's1' }, attachTo })
    await flushPromises()
    expect(document.body.textContent).toContain('会话不存在')
  })

  it('展示 workflow 步骤与当前步骤', async () => {
    mockGet.mockResolvedValue(cpData)
    wrapper = mount(CheckpointViewer, { props: { visible: true, sessionId: 's1' }, attachTo })
    await flushPromises()
    const text = document.body.textContent || ''
    expect(text).toContain('recommend')
    expect(text).toContain('profile_node')
    expect(text).toContain('summary_node')
    expect(text).toContain('当前: summary_node')
  })

  it('点击关闭按钮触发 close 事件', async () => {
    mockGet.mockResolvedValue(cpData)
    wrapper = mount(CheckpointViewer, { props: { visible: true, sessionId: 's1' }, attachTo })
    await flushPromises()
    const closeBtn = document.querySelector('.close-btn') as HTMLElement
    closeBtn?.click()
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('点击「继续运行」调用 resume 并显示成功结果', async () => {
    mockGet.mockResolvedValue(cpData)
    mockResume.mockResolvedValue({ success: true, workflow_type: 'recommend_workflow', resumed_from: 'summary_node', answer: '推荐结果' })
    wrapper = mount(CheckpointViewer, { props: { visible: true, sessionId: 's1' }, attachTo })
    await flushPromises()
    const resumeBtn = document.querySelector('.resume-btn') as HTMLElement
    resumeBtn?.click()
    await flushPromises()
    expect(mockResume).toHaveBeenCalledWith('s1')
    expect(document.body.textContent).toContain('已从断点继续完成')
  })

  it('resume 返回 error 时显示失败结果', async () => {
    mockGet.mockResolvedValue(cpData)
    mockResume.mockResolvedValue({ success: false, workflow_type: 'recommend_workflow', resumed_from: 'summary_node', answer: '', error: '数据缺失', failed_at: 'reason_node' })
    wrapper = mount(CheckpointViewer, { props: { visible: true, sessionId: 's1' }, attachTo })
    await flushPromises()
    const resumeBtn = document.querySelector('.resume-btn') as HTMLElement
    resumeBtn?.click()
    await flushPromises()
    expect(document.body.textContent).toContain('恢复失败')
    expect(document.body.textContent).toContain('reason_node')
  })

  it('resume 接口异常时显示失败结果', async () => {
    mockGet.mockResolvedValue(cpData)
    mockResume.mockRejectedValue({ response: { data: { detail: '断点恢复失败' } } })
    wrapper = mount(CheckpointViewer, { props: { visible: true, sessionId: 's1' }, attachTo })
    await flushPromises()
    const resumeBtn = document.querySelector('.resume-btn') as HTMLElement
    resumeBtn?.click()
    await flushPromises()
    expect(document.body.textContent).toContain('恢复失败')
    expect(document.body.textContent).toContain('断点恢复失败')
  })
})
