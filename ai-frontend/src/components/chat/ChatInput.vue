<template>
  <div class="chat-input-wrapper">
    <div class="toast" v-if="showToast">{{ toastMessage }}</div>
    <div class="image-preview" v-if="previewUrls.length > 0">
      <div class="preview-item" v-for="(url, i) in previewUrls" :key="i">
        <img :src="url" alt="preview" class="preview-img" />
        <button class="preview-remove" @click="removeImage(i)">✕</button>
      </div>
    </div>
    <div class="chat-input-container">
      <button class="upload-btn" @click="triggerUpload" title="上传图片">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
          <circle cx="8.5" cy="8.5" r="1.5"></circle>
          <polyline points="21 15 16 10 5 21"></polyline>
        </svg>
      </button>
      <input ref="fileInputRef" type="file" accept="image/*" multiple style="display:none" @change="onFileSelected" />
      <textarea
        ref="inputRef"
        v-model="inputText"
        class="chat-input"
        placeholder="输入消息开始对话..."
        rows="1"
        @keydown="handleKeydown"
        @input="autoResize"
      ></textarea>
      <button
        class="send-btn"
        :disabled="isDisabled"
        @click="handleSend"
      >
        <svg v-if="!isSending" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="22" y1="2" x2="11" y2="13"></line>
          <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
        </svg>
        <svg v-else class="spinner" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10" stroke-dasharray="60" stroke-dashoffset="20"></circle>
        </svg>
      </button>
    </div>
    <div class="input-hint">
      <span>按 Enter 发送，Shift + Enter 换行，支持图片上传</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onBeforeUnmount } from 'vue'

const props = defineProps<{
  isStreaming?: boolean
}>()

const emit = defineEmits<{
  (e: 'send', message: string, imageUrls?: string[]): void
}>()

const inputText = ref('')
const isSending = ref(false)
const previewUrls = ref<string[]>([])
const imageSizes = ref<number[]>([])
const fileInputRef = ref<HTMLInputElement>()
const inputRef = ref<HTMLTextAreaElement>()
const showToast = ref(false)
const toastMessage = ref('')

// nginx client_max_body_size=8m；base64 编码放大 ~4/3，
// 所以总原始图片大小上限 5MB（对应 base64 ~6.7MB，含 JSON 结构仍 < 8MB）
const MAX_TOTAL_IMAGE_BYTES = 5 * 1024 * 1024

// 按钮禁用条件：本地未发送中 + 全局流式未进行 + 有内容
const isDisabled = computed(() => {
  if (isSending.value || props.isStreaming) return true
  return !inputText.value.trim() && previewUrls.value.length === 0
})

// 跟踪所有 setTimeout，组件卸载时清理，避免回调访问已销毁的状态
const pendingTimers = new Set<ReturnType<typeof setTimeout>>()

function showToastMsg(msg: string) {
  toastMessage.value = msg
  showToast.value = true
  const timer = setTimeout(() => {
    showToast.value = false
    pendingTimers.delete(timer)
  }, 3000)
  pendingTimers.add(timer)
}

onBeforeUnmount(() => {
  for (const timer of pendingTimers) {
    clearTimeout(timer)
  }
  pendingTimers.clear()
  // 释放 blob URL 防止内存泄漏
  for (const url of previewUrls.value) {
    if (url.startsWith('blob:')) {
      try { URL.revokeObjectURL(url) } catch { /* ignore */ }
    }
  }
  previewUrls.value = []
  imageSizes.value = []
})

function triggerUpload() {
  fileInputRef.value?.click()
}

function onFileSelected(e: Event) {
  const files = (e.target as HTMLInputElement).files
  if (!files) return
  const currentTotal = imageSizes.value.reduce((a, b) => a + b, 0)
  for (const file of Array.from(files)) {
    if (!file.type.startsWith('image/')) {
      showToastMsg(`不支持的文件类型：${file.type || '未知'}`)
      continue
    }
    if (file.size > 5 * 1024 * 1024) {
      showToastMsg(`文件过大：${file.name}（超过 5MB 限制）`)
      continue
    }
    if (currentTotal + file.size > MAX_TOTAL_IMAGE_BYTES) {
      showToastMsg('图片总大小超过 5MB 限制，请减少图片数量或压缩后重试')
      continue
    }
    const reader = new FileReader()
    reader.onload = () => {
      const dataUrl = reader.result as string
      previewUrls.value.push(dataUrl)
      imageSizes.value.push(file.size)
    }
    reader.readAsDataURL(file)
  }
  if (fileInputRef.value) fileInputRef.value.value = ''
}

function removeImage(i: number) {
  previewUrls.value.splice(i, 1)
  imageSizes.value.splice(i, 1)
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function handleSend() {
  if (isSending.value) return
  const text = inputText.value.trim()
  const urls = [...previewUrls.value]
  if (!text && urls.length === 0) return

  isSending.value = true
  emit('send', text, urls)
  inputText.value = ''
  previewUrls.value = []
  imageSizes.value = []

  if (inputRef.value) {
    inputRef.value.style.height = 'auto'
  }

  // 兜底：500ms 后强制重置 isSending（防止父组件忘记 setReady）
  setTimeout(() => {
    isSending.value = false
  }, 500)
}

defineExpose({
  setReady() {
    isSending.value = false
  }
})

function autoResize() {
  if (inputRef.value) {
    inputRef.value.style.height = 'auto'
    inputRef.value.style.height = Math.min(inputRef.value.scrollHeight, 200) + 'px'
  }
}
</script>

<style scoped>
.toast {
  padding: 8px 16px;
  margin-bottom: 8px;
  background: #fef2f2;
  color: #dc2626;
  border: 1px solid #fca5a5;
  border-radius: var(--radius-btn);
  font-size: 13px;
  animation: fadeIn 0.2s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

.chat-input-wrapper {
  padding: var(--space-md);
  background: var(--color-bg-card);
  border-top: 1px solid var(--color-border);
}

.image-preview {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.preview-item {
  position: relative;
  width: 80px;
  height: 80px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--color-border);
}

.preview-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.preview-remove {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: rgba(0,0,0,0.6);
  color: #fff;
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  border: none;
}

.chat-input-container {
  display: flex;
  align-items: flex-end;
  gap: var(--space-sm);
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: 24px;
  padding: var(--space-sm) var(--space-sm) var(--space-sm) var(--space-md);
  transition: border-color var(--transition-fast);
}

.chat-input-container:focus-within {
  border-color: var(--color-primary);
}

.upload-btn {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: transparent;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  cursor: pointer;
  transition: all var(--transition-fast);
  border: none;
  margin-bottom: 2px;
}

.upload-btn:hover {
  background: var(--color-bg-card);
  color: var(--color-primary);
}

.chat-input {
  flex: 1;
  background: transparent;
  resize: none;
  font-size: 15px;
  line-height: 1.5;
  max-height: 200px;
  color: var(--color-text);
  padding: 6px 8px 6px 0;
}

.chat-input::placeholder {
  color: var(--color-text-secondary);
}

.send-btn {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--color-primary);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all var(--transition-fast);
  border: none;
  cursor: pointer;
}

.send-btn:hover:not(:disabled) {
  transform: scale(1.05);
}

.send-btn:disabled {
  background: var(--color-border);
  cursor: not-allowed;
}

.spinner {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.input-hint {
  text-align: center;
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-top: var(--space-sm);
}
</style>
