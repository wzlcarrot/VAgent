/**
 * Toast 组件测试 - 类型图标映射、自动关闭定时器、清理
 *
 * 说明：Toast 的 watcher 无 immediate，图标/定时器在 visible 由 false→true 转换时初始化。
 * 真实用法中 toastState.visible 也是 false→true，故测试按此挂载以贴近实际行为。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import Toast from '@/components/common/Toast.vue'

const attachTo = typeof document !== 'undefined' ? document.body : undefined

async function showToast(props: Record<string, unknown> = {}) {
  const wrapper = mount(Toast, {
    props: { visible: false, message: '', ...props },
    attachTo,
  })
  await nextTick()
  await wrapper.setProps({ visible: true }) // 触发 false→true 初始化
  await nextTick()
  return wrapper
}

describe('Toast 组件', () => {
  let wrapper: ReturnType<typeof mount>

  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    wrapper?.unmount()
    document.body.innerHTML = ''
    vi.useRealTimers()
  })

  it('visible=true 时渲染消息', async () => {
    wrapper = await showToast({ message: '操作成功' })
    expect(document.body.textContent).toContain('操作成功')
  })

  it('visible=false 时不渲染', async () => {
    wrapper = mount(Toast, { props: { visible: false, message: 'x' }, attachTo })
    await nextTick()
    expect(document.querySelector('.toast-container')).toBeNull()
  })

  it('type=success 显示成功图标', async () => {
    wrapper = await showToast({ message: 'm', type: 'success' })
    expect(document.querySelector('.toast-icon')?.textContent).toBe('✅')
  })

  it('type=error 显示错误图标', async () => {
    wrapper = await showToast({ message: 'm', type: 'error' })
    expect(document.querySelector('.toast-icon')?.textContent).toBe('❌')
  })

  it('默认 type=info 显示信息图标', async () => {
    wrapper = await showToast({ message: 'm' })
    expect(document.querySelector('.toast-icon')?.textContent).toBe('ℹ️')
  })

  it('duration 到期后自动关闭（emit update:visible=false）', async () => {
    wrapper = await showToast({ message: 'm', duration: 3000 })
    expect(wrapper.emitted('update:visible')).toBeFalsy()

    await vi.advanceTimersByTimeAsync(3000)
    expect(wrapper.emitted('update:visible')).toBeTruthy()
    expect(wrapper.emitted('update:visible')![0][0]).toBe(false)
  })

  it('自定义 duration 生效', async () => {
    wrapper = await showToast({ message: 'm', duration: 500 })
    await vi.advanceTimersByTimeAsync(400)
    expect(wrapper.emitted('update:visible')).toBeFalsy()
    await vi.advanceTimersByTimeAsync(100)
    expect(wrapper.emitted('update:visible')).toBeTruthy()
  })

  it('visible 变 false 时清除定时器', async () => {
    wrapper = await showToast({ message: 'm', duration: 10000 })
    await wrapper.setProps({ visible: false })
    await nextTick()
    await vi.advanceTimersByTimeAsync(20000)
    expect(wrapper.emitted('update:visible')).toBeFalsy()
  })
})
