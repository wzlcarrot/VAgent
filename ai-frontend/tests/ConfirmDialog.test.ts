/**
 * useNotify + ConfirmDialog 单元测试
 */
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { useNotify, showToast as globalShowToast, showConfirm as globalShowConfirm } from '@/composables/useNotify'

describe('useNotify', () => {
  it('showToast 应更新 toastState', async () => {
    const { showToast, toastState } = useNotify()
    showToast('测试消息', 'success')
    await flushPromises()
    expect(toastState.message).toBe('测试消息')
    expect(toastState.type).toBe('success')
    expect(toastState.visible).toBe(true)
  })

  it('showConfirm 应返回 Promise<bool>', async () => {
    const { showConfirm } = useNotify()
    const promise = showConfirm({ message: '确认?' })
    expect(promise).toBeInstanceOf(Promise)
    // 不 resolve，pending
    let resolved = false
    promise.then(() => { resolved = true })
    await flushPromises()
    expect(resolved).toBe(false)
  })
})

describe('ConfirmDialog', () => {
  // ConfirmDialog 用 Teleport to="body"，必须 attachTo 才能找到 DOM
  const attachTo = typeof document !== 'undefined' ? document.body : undefined

  it('visible=false 时不渲染内容', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { visible: false, message: 'test' },
      attachTo,
    })
    expect(document.querySelector('.confirm-dialog')).toBeNull()
    wrapper.unmount()
  })

  it('visible=true 时渲染标题和消息', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { visible: true, title: '删除', message: '确定?' },
      attachTo,
    })
    const titleEl = document.querySelector('.confirm-title')
    const msgEl = document.querySelector('.confirm-message')
    expect(titleEl?.textContent).toBe('删除')
    expect(msgEl?.textContent).toBe('确定?')
    wrapper.unmount()
  })

  it('点击确认按钮应该 emit confirm', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { visible: true, message: 'ok?' },
      attachTo,
    })
    const btn = document.querySelector('.btn-confirm') as HTMLElement
    btn?.click()
    await flushPromises()
    expect(wrapper.emitted('confirm')).toBeTruthy()
    wrapper.unmount()
  })

  it('点击取消按钮应该 emit cancel', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { visible: true, message: 'ok?' },
      attachTo,
    })
    const btn = document.querySelector('.btn-cancel') as HTMLElement
    btn?.click()
    await flushPromises()
    expect(wrapper.emitted('cancel')).toBeTruthy()
    wrapper.unmount()
  })

  it('点击 overlay 应该取消', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { visible: true, message: 'ok?' },
      attachTo,
    })
    const overlay = document.querySelector('.confirm-overlay') as HTMLElement
    overlay?.click()
    await flushPromises()
    expect(wrapper.emitted('cancel')).toBeTruthy()
    wrapper.unmount()
  })

  it('danger 变体应该加 danger class', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { visible: true, message: '危险', variant: 'danger' },
      attachTo,
    })
    const btn = document.querySelector('.btn-confirm')
    expect(btn?.classList.contains('danger')).toBe(true)
    wrapper.unmount()
  })

  it('默认确认按钮文案是"确定"', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { visible: true, message: 'test' },
      attachTo,
    })
    const btn = document.querySelector('.btn-confirm')
    expect(btn?.textContent).toBe('确定')
    wrapper.unmount()
  })

  it('默认取消按钮文案是"取消"', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { visible: true, message: 'test' },
      attachTo,
    })
    const btn = document.querySelector('.btn-cancel')
    expect(btn?.textContent).toBe('取消')
    wrapper.unmount()
  })

  it('自定义按钮文案应该覆盖默认', () => {
    const wrapper = mount(ConfirmDialog, {
      props: {
        visible: true,
        message: 'test',
        confirmText: '是的',
        cancelText: '不要',
      },
      attachTo,
    })
    const confirmBtn = document.querySelector('.btn-confirm')
    const cancelBtn = document.querySelector('.btn-cancel')
    expect(confirmBtn?.textContent).toBe('是的')
    expect(cancelBtn?.textContent).toBe('不要')
    wrapper.unmount()
  })
})