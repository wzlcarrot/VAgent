<template>
  <div id="app" :data-font-size="settingsStore.fontSize">
    <router-view v-slot="{ Component }">
      <Transition name="page" mode="out-in">
        <component :is="Component" v-if="!hasError" />
        <div v-else class="error-boundary">
          <div class="error-icon">😵</div>
          <h2>页面出错了</h2>
          <p class="error-message">{{ errorMessage }}</p>
          <button class="retry-btn" @click="handleRetry">刷新页面</button>
        </div>
      </Transition>
    </router-view>
    <Toast v-if="toastState.visible" v-bind="toastState" @update:visible="onToastUpdate" />
    <ConfirmDialog
      v-if="confirmState.visible"
      v-bind="confirmState"
      @confirm="onConfirmOk"
      @cancel="onConfirmCancel"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onErrorCaptured, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useSettingsStore } from '@/stores/settings'
import { useChatStore } from '@/stores/chat'
import { useUserStore } from '@/stores/user'
import { useNotify } from '@/composables/useNotify'
import Toast from '@/components/common/Toast.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'

const settingsStore = useSettingsStore()
const chatStore = useChatStore()
const userStore = useUserStore()
const router = useRouter()
const route = useRoute()

const { toastState, confirmState, onConfirmResolve, hideToast } = useNotify()

const hasError = ref(false)
const errorMessage = ref('未知错误')

onErrorCaptured((err: unknown) => {
  hasError.value = true
  errorMessage.value = err instanceof Error ? err.message : '未知错误'
  console.error('[ErrorBoundary]', err)
  return false
})

watch(() => route.path, () => {
  hasError.value = false
})

function handleRetry() {
  hasError.value = false
  errorMessage.value = ''
  window.location.reload()
}

function onToastUpdate(visible: boolean) {
  if (!visible) hideToast()
}

function onConfirmOk() {
  onConfirmResolve(true)
}

function onConfirmCancel() {
  onConfirmResolve(false)
}

onMounted(() => {
  settingsStore.applyTheme(settingsStore.theme)
  chatStore.loadUserSessions()
  window.addEventListener('auth:unauthorized', () => {
    // 清除内存+localStorage 登录态，避免 isLoggedIn 仍为 true 导致 login→home 跳转死循环
    userStore.logout()
    router.push('/login')
  })
})
</script>

<style>
#app {
  height: 100%;
}

.page-enter-active,
.page-leave-active {
  transition: all 0.3s ease;
}

.page-enter-from {
  opacity: 0;
  transform: translateY(20px);
}

.page-leave-to {
  opacity: 0;
  transform: translateY(-20px);
}

.error-boundary {
  height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 40px;
  background: #1a1a2e;
  color: #eee;
}

.error-icon {
  font-size: 64px;
  margin-bottom: 16px;
}

.error-boundary h2 {
  margin: 0 0 12px;
  font-size: 24px;
  color: #ff6b6b;
}

.error-message {
  margin: 0 0 24px;
  font-size: 14px;
  color: #888;
  max-width: 400px;
  word-break: break-word;
}

.retry-btn {
  padding: 10px 24px;
  background: #4a6cf7;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  transition: opacity 0.2s;
}

.retry-btn:hover {
  opacity: 0.9;
}
</style>
