/**
 * 全局通知 composable — 替代原生 alert/confirm
 * 用法：
 *   const { showToast, showConfirm } = useNotify()
 *   showToast('操作成功', 'success')
 *   const ok = await showConfirm({ title: '确认', message: '...' })
 */
import { reactive, readonly } from 'vue'

interface ToastState {
  visible: boolean
  message: string
  type: 'info' | 'success' | 'error' | 'warning'
  duration: number
}

interface ConfirmState {
  visible: boolean
  title: string
  message: string
  confirmText: string
  cancelText: string
  variant: 'default' | 'danger'
  resolve: ((v: boolean) => void) | null
}

const toastState = reactive<ToastState>({
  visible: false,
  message: '',
  type: 'info',
  duration: 3000,
})

const confirmState = reactive<ConfirmState>({
  visible: false,
  title: '确认',
  message: '',
  confirmText: '确定',
  cancelText: '取消',
  variant: 'default',
  resolve: null,
})

let toastTimer: ReturnType<typeof setTimeout> | null = null

function showToast(message: string, type: ToastState['type'] = 'info', duration = 3000) {
  toastState.message = message
  toastState.type = type
  toastState.duration = duration
  toastState.visible = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toastState.visible = false
    toastTimer = null
  }, duration)
}

function hideToast() {
  toastState.visible = false
  if (toastTimer) {
    clearTimeout(toastTimer)
    toastTimer = null
  }
}

function showConfirm(options: {
  title?: string
  message: string
  confirmText?: string
  cancelText?: string
  variant?: 'default' | 'danger'
}): Promise<boolean> {
  return new Promise((resolve) => {
    confirmState.title = options.title ?? '确认'
    confirmState.message = options.message
    confirmState.confirmText = options.confirmText ?? '确定'
    confirmState.cancelText = options.cancelText ?? '取消'
    confirmState.variant = options.variant ?? 'default'
    confirmState.resolve = resolve
    confirmState.visible = true
  })
}

function onConfirmResolve(ok: boolean) {
  if (confirmState.resolve) {
    confirmState.resolve(ok)
    confirmState.resolve = null
  }
  confirmState.visible = false
}

export function useNotify() {
  return {
    toastState: readonly(toastState),
    confirmState: readonly(confirmState),
    showToast,
    hideToast,
    showConfirm,
    onConfirmResolve,
  }
}