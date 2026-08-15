/**
 * Toast 通知组件 - 替代原生 alert()
 */
<template>
  <Teleport to="body">
    <Transition name="toast">
      <div v-if="visible" class="toast-container" :class="type">
        <span class="toast-icon">{{ icon }}</span>
        <span class="toast-message">{{ message }}</span>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

interface Props {
  visible: boolean
  message: string
  type?: 'info' | 'success' | 'error' | 'warning'
  duration?: number
}

const props = withDefaults(defineProps<Props>(), {
  type: 'info',
  duration: 3000,
})

const emit = defineEmits<{
  (e: 'update:visible', v: boolean): void
}>()

let timer: ReturnType<typeof setTimeout> | null = null

const iconMap = {
  info: 'ℹ️',
  success: '✅',
  error: '❌',
  warning: '⚠️',
}

const icon = ref('ℹ️')

watch(() => props.visible, (val) => {
  icon.value = iconMap[props.type]
  if (val) {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      emit('update:visible', false)
    }, props.duration)
  } else if (timer) {
    clearTimeout(timer)
    timer = null
  }
})
</script>

<style scoped>
.toast-container {
  position: fixed;
  top: 80px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 10000;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  background: var(--color-bg-card, #fff);
  border-radius: var(--radius-btn, 8px);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  font-size: 14px;
  color: var(--color-text, var(--color-primary-strong));
  max-width: 90vw;
}
.toast-container.success {
  border-left: 4px solid var(--color-success);
}
.toast-container.error {
  border-left: 4px solid var(--color-danger);
}
.toast-container.warning {
  border-left: 4px solid var(--color-warning);
}
.toast-container.info {
  border-left: 4px solid var(--color-primary, var(--color-primary-light));
}
.toast-icon {
  font-size: 16px;
}
.toast-message {
  word-break: break-word;
}
.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.2s, transform 0.2s;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translate(-50%, -10px);
}
</style>