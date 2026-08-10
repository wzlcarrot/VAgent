<template>
  <div class="home-view">
    <AppHeader />
    <div class="main-layout">
      <AppSidebar />
      <main class="chat-area">
        <!-- Empty State -->
        <div class="empty-state" v-if="messages.length === 0">
          <div class="welcome-avatar">
            <span class="welcome-icon">🤖</span>
          </div>
          <h2>你好！我是 ViewHub AI</h2>
          <p class="welcome-text">
            我可以帮你<span class="highlight">推荐视频</span>、<span class="highlight">查询播放数据</span>、<span class="highlight">解答平台问题</span>。
            试试点击下面的快捷操作👇
          </p>
          <QuickActions
            class="quick-actions-container"
            @select="handleQuickAction"
          />
        </div>

        <!-- Messages -->
        <div class="messages-container" ref="messagesContainer">
          <template v-for="(message, msgIndex) in messages" :key="message.id">
            <MessageBubble
              :message="message"
              :sessionId="currentSessionId ?? undefined"
              :messageIndex="msgIndex"
              :isStreaming="msgIndex === messages.length - 1 && chatStore.isStreaming"
              @retry="handleRetry"
            />

            <!-- Video Cards for Recommendations -->
            <div v-if="message.videos && message.videos.length > 0" class="video-recommendations">
              <div class="recommendation-header">
                <span class="recommendation-icon">◈</span>
                <span class="recommendation-title">为你推荐</span>
              </div>
              <div class="video-list">
                <VideoCard
                  v-for="video in message.videos"
                  :key="video.videoId"
                  :video="video"
                  :reason="getRecommendationReason(video.videoId)"
                  :videoUrl="getVideoUrl(video.videoId)"
                  :disabled="!videoServiceAvailable"
                  @play="handleVideoPlay"
                />
              </div>
            </div>
          </template>
        </div>

        <WorkflowIndicator
          :visible="showWorkflow"
          :stage="workflowStage"
          :label="workflowLabel"
        />

        <!-- Input -->
        <ChatInput :isStreaming="chatStore.isStreaming" @send="handleSendWithImages" />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useChatStore } from '@/stores/chat'
import { useUserStore } from '@/stores/user'
import { smartChatStream, getChatHistory } from '@/api/chat'
import type { Message } from '@/types'
import AppHeader from '@/components/layout/AppHeader.vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import MessageBubble from '@/components/chat/MessageBubble.vue'
import ChatInput from '@/components/chat/ChatInput.vue'
import WorkflowIndicator from '@/components/chat/WorkflowIndicator.vue'
import QuickActions from '@/components/chat/QuickActions.vue'
import VideoCard from '@/components/video/VideoCard.vue'

const chatStore = useChatStore()
const userStore = useUserStore()
const route = useRoute()
const { messages, currentSessionId } = storeToRefs(chatStore)

const messagesContainer = ref<HTMLElement>()
const pendingImages = ref<string[]>([])
const showWorkflow = ref(false)
const workflowStage = ref('')
const workflowLabel = ref('')
const recommendationReasons = ref<Record<string, string>>({})
const videoServiceAvailable = ref(true)

// 当前进行中的流式请求控制器（session 切换 / 卸载时 abort，避免浪费 LLM token）
let activeStreamController: AbortController | null = null

const _videoIdPatterns = [
  /(?:视频)?id[号是:：\s]*([\w-]+)/i,
  /video[_-]?id[号是:：\s]*([\w-]+)/i,
]

async function checkVideoService() {
  try {
    const base = import.meta.env.VITE_VIDEO_BASE_URL || 'http://localhost:7071'
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 2000)
    await fetch(base, { method: 'HEAD', signal: controller.signal })
    clearTimeout(timeout)
    videoServiceAvailable.value = true
  } catch {
    videoServiceAvailable.value = false
  }
}

function _extractVideoId(text: string): string | null {
  for (const pattern of _videoIdPatterns) {
    const m = text.match(pattern)
    if (m && m[1] && m[1].length >= 4) return m[1]
  }
  return null
}

function _needsWorkflowIndicator(text: string): boolean {
  return /讲解|重点|内容|推荐/.test(text)
}

function _createBatchedUpdater<T extends object>(apply: (next: T) => void) {
  let pending: T | null = null
  let rafId: number | null = null
  return (next: T) => {
    pending = next
    if (rafId !== null) return
    rafId = requestAnimationFrame(() => {
      if (pending) apply(pending)
      pending = null
      rafId = null
    })
  }
}

const _onSessionSwitched = (e: Event) => {
  const detail = (e as CustomEvent<{ sessionId: string }>).detail
  if (detail?.sessionId) {
    activeStreamController?.abort()  // 切换会话：取消进行中的流，避免浪费 LLM token
    loadSessionHistory(detail.sessionId)
  }
}

// 初始化会话
onMounted(() => {
  // 优先使用 URL query 中的 sessionId（来自 HistoryView 跳转）
  const querySessionId = route.query.session as string | undefined
  if (querySessionId) {
    chatStore.setCurrentSessionId(querySessionId)
    chatStore.clearMessages()
    loadSessionHistory(querySessionId)
  } else if (currentSessionId.value) {
    loadSessionHistory(currentSessionId.value)
  } else {
    chatStore.createSession()
  }

  checkVideoService()
  window.addEventListener('session-switched', _onSessionSwitched)
})

onUnmounted(() => {
  window.removeEventListener('session-switched', _onSessionSwitched)
  activeStreamController?.abort()
})

async function loadSessionHistory(sessionId: string) {
  if (!userStore.user?.userId) {
    console.warn('[HomeView] loadSessionHistory aborted: no userId')
    return
  }

  try {
    const history = await getChatHistory(
      sessionId,
      100
    )

    chatStore.clearCurrentSession()

    const sortedHistory = [...history].sort((a, b) => {
      const timeA = a.timestamp ? new Date(a.timestamp).getTime() : 0
      const timeB = b.timestamp ? new Date(b.timestamp).getTime() : 0
      return timeA - timeB
    })

    for (const msg of sortedHistory) {
      chatStore.addMessage({
        role: msg.role as 'user' | 'assistant',
        content: msg.content,
        status: 'success',
        videos: msg.videos || undefined,
        reasons: msg.reasons || undefined,
      } as any)
    }
    // 同步把 reasons 灌进 recommendationReasons（这样历史视频卡也能显示 reason）
    for (const msg of sortedHistory) {
      if (msg.role === 'assistant' && msg.videos && msg.reasons) {
        msg.videos.forEach((v: any, i: number) => {
          if (msg.reasons && msg.reasons[i] && v.videoId) {
            recommendationReasons.value[v.videoId] = msg.reasons[i]
          }
        })
      }
    }
  } catch (error) {
    console.error('[HomeView] Failed to load chat history:', error)
  }
}

function _scrollToBottom() {
  const el = messagesContainer.value
  if (!el) return
  const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 150
  if (isNearBottom) el.scrollTop = el.scrollHeight
}

watch(messages, () => {
  nextTick(_scrollToBottom)
}, { flush: 'post' })

async function handleSend(text: string) {
  showWorkflow.value = false

  const imgUrls = [...pendingImages.value]
  pendingImages.value = []

  const extractedVideoId = _extractVideoId(text)
  const needsWorkflow = _needsWorkflowIndicator(text)

  chatStore.addMessage({
    role: 'user',
    content: text,
    status: 'success',
    imageUrls: imgUrls.length > 0 ? imgUrls : undefined,
  })

  if (needsWorkflow) {
    showWorkflow.value = true
  }

  const aiMessageId = chatStore.addMessage({
    role: 'assistant',
    content: '',
    status: 'sending',
  }).id

  await streamAiResponse(text, aiMessageId, extractedVideoId, imgUrls)
}

async function handleRetry(messageId: string) {
  const failedIndex = chatStore.messages.findIndex(m => m.id === messageId)
  if (failedIndex <= 0) return

  const failedMsg = chatStore.messages[failedIndex]
  if (failedMsg.role !== 'assistant' || failedMsg.status !== 'error') return

  const userMsg = chatStore.messages[failedIndex - 1]
  if (!userMsg || userMsg.role !== 'user') return

  const text = userMsg.content
  const imgUrls = userMsg.imageUrls || []

  chatStore.updateMessage(messageId, {
    content: '',
    status: 'sending',
    videos: undefined,
  })

  await streamAiResponse(text, messageId, _extractVideoId(text), imgUrls)
}

// 当前进行中的流式请求控制器（session 切换 / 卸载时 abort，避免浪费 LLM token）
async function streamAiResponse(text: string, aiMessageId: string, extractedVideoId: string | null = null, imgUrls: string[] = []) {
  chatStore.isStreaming = true

  let fullContent = ''
  workflowStage.value = ''
  workflowLabel.value = ''

  const controller = new AbortController()
  activeStreamController = controller

  const batchedUpdateContent = _createBatchedUpdater<Partial<Message>>(
    (next) => chatStore.updateMessage(aiMessageId, next)
  )

  try {
    for await (const event of smartChatStream(text, currentSessionId.value || undefined, extractedVideoId || undefined, userStore.user?.userId, userStore.user?.token, imgUrls.length > 0 ? imgUrls : undefined, controller.signal)) {
      if (event.type === 'status') {
        workflowStage.value = event.stage
        workflowLabel.value = event.label
      } else if (event.type === 'text') {
        fullContent += event.content
        batchedUpdateContent({ content: fullContent, status: 'sending' })
      } else if (event.type === 'videos') {
        chatStore.updateMessage(aiMessageId, { videos: event.videos })
        event.videos.forEach((v, i) => {
          if (event.reasons[i]) {
            recommendationReasons.value[v.videoId] = event.reasons[i]
          }
        })
      }
    }

    chatStore.updateMessage(aiMessageId, {
      content: fullContent,
      status: 'success',
    })
  } catch (error: unknown) {
    // abort 属于主动取消（切 session / 卸载），不显示错误
    if (controller.signal.aborted) {
      chatStore.updateMessage(aiMessageId, { status: 'success' })
      return
    }
    const msg = error instanceof Error ? error.message : '请求失败，请稍后重试'
    chatStore.updateMessage(aiMessageId, {
      content: fullContent + (fullContent ? '\n\n' : '') + '⚠️ ' + msg,
      status: 'error',
    })
  } finally {
    if (activeStreamController === controller) {
      activeStreamController = null
    }
    chatStore.isStreaming = false
    chatStore.finalizeStreaming()
    showWorkflow.value = false

    workflowStage.value = ''
    workflowLabel.value = ''
    chatStore.needsSidebarRefresh = true
  }
}

function handleSendWithImages(text: string, imageUrls?: string[]) {
  if (imageUrls && imageUrls.length > 0) {
    pendingImages.value = imageUrls
  }
  handleSend(text)
}

function handleQuickAction(prompt: string) {
  pendingImages.value = []
  handleSend(prompt)
}

function getRecommendationReason(videoId: string): string {
  return recommendationReasons.value[videoId] || ''
}

function getVideoUrl(videoId: string): string {
  const base = import.meta.env.VITE_VIDEO_BASE_URL || 'http://localhost:7071'
  return `${base}/video/${videoId}`
}

function handleVideoPlay(video: { videoId: string }) {
  const url = getVideoUrl(video.videoId)
  window.open(url, '_blank', 'noopener,noreferrer')
}
</script>

<style scoped>
.home-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.main-layout {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.chat-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 80px var(--space-xl);
  overflow: hidden;
}

.welcome-avatar {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: linear-gradient(135deg, #4a6cf7, #6366f1);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
  box-shadow: 0 4px 16px rgba(74, 108, 247, 0.3);
}

.welcome-icon {
  font-size: 32px;
}

.empty-state h2 {
  margin: 0 0 8px;
  font-size: 22px;
  color: #1a1a2e;
}

.welcome-text {
  margin: 0 0 24px;
  font-size: 15px;
  color: #606266;
  line-height: 1.6;
  max-width: 400px;
}

.welcome-text .highlight {
  color: #4a6cf7;
  font-weight: 500;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: var(--space-sm);
}

.empty-state h2 {
  font-size: 22px;
  font-weight: 600;
  margin-bottom: var(--space-lg);
  color: var(--color-text);
}

.quick-actions-container {
  margin-top: 0;
}

.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-md);
}

/* 输入框上方的指示器区域 */
.input-indicator-area {
  min-height: 32px;
  padding: 0 var(--space-md);
  display: flex;
  align-items: center;
}

.video-recommendations {
  margin: var(--space-md) 0;
  padding: var(--space-md);
  background: linear-gradient(135deg, rgba(10, 10, 26, 0.6), rgba(22, 33, 62, 0.6));
  border: 1px solid rgba(74, 108, 247, 0.2);
  border-radius: var(--radius-card);
  position: relative;
  overflow: hidden;
}

.video-recommendations::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, #4a6cf7, transparent);
  animation: scan-h 3s linear infinite;
}

@keyframes scan-h {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

.recommendation-header {
  margin-bottom: var(--space-sm);
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.recommendation-title {
  font-size: 14px;
  font-weight: 600;
  color: #4a6cf7;
  text-transform: uppercase;
  letter-spacing: 1px;
  text-shadow: 0 0 10px rgba(74, 108, 247, 0.5);
}

.recommendation-icon {
  color: #00d9ff;
  font-size: 16px;
  text-shadow: 0 0 8px rgba(0, 217, 255, 0.6);
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.video-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
</style>
