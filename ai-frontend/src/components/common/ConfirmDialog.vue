<template>
  <Teleport to="body">
    <Transition name="dialog">
      <div v-if="visible" class="confirm-overlay" @click.self="onCancel">
        <div class="confirm-dialog" role="dialog" aria-modal="true">
          <h3 v-if="title" class="confirm-title">{{ title }}</h3>
          <p class="confirm-message">{{ message }}</p>
          <div class="confirm-actions">
            <button class="btn-cancel" @click="onCancel" :disabled="loading">
              {{ cancelText }}
            </button>
            <button
              class="btn-confirm"
              :class="{ danger: variant === 'danger' }"
              @click="onConfirm"
              :disabled="loading"
            >
              {{ loading ? '处理中...' : confirmText }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref } from 'vue'

interface Props {
  visible: boolean
  title?: string
  message: string
  confirmText?: string
  cancelText?: string
  variant?: 'default' | 'danger'
}

const props = withDefaults(defineProps<Props>(), {
  title: '确认',
  confirmText: '确定',
  cancelText: '取消',
  variant: 'default',
})

// 防止 vue-tsc 报未使用变量
const _props = props
void _props

const emit = defineEmits<{
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()

const loading = ref(false)

function onConfirm() {
  loading.value = true
  emit('confirm')
}

function onCancel() {
  if (loading.value) return
  emit('cancel')
}
</script>

<style scoped>
.confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  animation: fadeIn 0.18s ease;
}
.confirm-dialog {
  background: var(--color-bg-card, #fff);
  border-radius: var(--radius-card, 12px);
  padding: 24px;
  max-width: 420px;
  width: calc(100% - 32px);
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.18);
  animation: slideUp 0.22s ease;
}
.confirm-title {
  margin: 0 0 12px;
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text, #1a1a2e);
}
.confirm-message {
  margin: 0 0 20px;
  font-size: 14px;
  color: var(--color-text-secondary, #555);
  line-height: 1.5;
  word-break: break-word;
}
.confirm-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
.btn-cancel,
.btn-confirm {
  padding: 8px 16px;
  border-radius: var(--radius-btn, 8px);
  font-size: 14px;
  cursor: pointer;
  border: 1px solid var(--color-border, #e5e5e5);
  background: transparent;
  color: var(--color-text-secondary, #555);
  transition: all 0.15s;
}
.btn-cancel:hover:not(:disabled),
.btn-confirm:hover:not(:disabled) {
  background: var(--color-bg, #f5f5f7);
}
.btn-confirm {
  background: var(--color-primary, #4a6cf7);
  color: #fff;
  border-color: var(--color-primary, #4a6cf7);
}
.btn-confirm.danger {
  background: var(--color-danger);
  border-color: var(--color-danger);
}
.btn-confirm.danger:hover:not(:disabled) {
  background: #b91c1c;
}
.btn-cancel:disabled,
.btn-confirm:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.dialog-enter-active,
.dialog-leave-active {
  transition: opacity 0.2s;
}
.dialog-enter-from,
.dialog-leave-to {
  opacity: 0;
}
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes slideUp {
  from { transform: translateY(20px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}
</style>