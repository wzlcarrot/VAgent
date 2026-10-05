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
          <p class="welcome-text" v-if="currentVideoId">
            当前视频上下文已就绪，我可以帮你<span class="highlight">回答当前视频问题</span>、
            <span class="highlight">推荐类似视频</span>，也可以<span class="highlight">查询你的播放数据</span>。
          </p>
          <p class="welcome-text" v-else>
            我可以帮你<span class="highlight">推荐视频</span>、<span class="highlight">查询播放数据</span>、
            <span class="highlight">解答平台问题</span>。从播放页进入可自动带入当前视频。
          </p>
          <p class="disclaimer-text">AI 回答仅供参考；个人数据仅用于你的账号内查询。</p>
          <QuickActions
            class="quick-actions-container"
            :current-video-id="currentVideoId"
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
              :userQuestion="msgIndex > 0 && messages[msgIndex - 1]?.role === 'user' ? messages[msgIndex - 1].content : ''"
              @retry="handleRetry"
              @rebatch="handleRebatch"
              @video-click="trackVideoClick"
            />
          </template>
        </div>

        <WorkflowIndicator
          :visible="showWorkflow || chatStore.isStreaming"
          :stage="workflowStage"
          :label="workflowLabel"
          :route="workflowRoute"
        />
        <ToolProgressBar v-if="chatStore.isStreaming" :tools="activeTools" />

        <!-- Input -->
        <ChatInput :isStreaming="chatStore.isStreaming" @send="handleSendWithImages" @stop="handleStopStream" />

        <ConfirmDialog
          :visible="!!pendingApproval"
          title="工具调用需确认"
          :message="approvalMessage"
          confirm-text="允许执行"
          cancel-text="拒绝"
          @confirm="onApprovalConfirm"
          @cancel="onApprovalDeny"
        />

        <button
          v-if="isDev"
          class="harness-debug-btn"
          type="button"
          title="Harness 调试"
          @click="showHarnessDebug = true"
        >
          Harness
        </button>
        <HarnessDebugPanel
          :visible="showHarnessDebug"
          :session-id="currentSessionId"
          :live-events="harnessLiveEvents"
          @close="showHarnessDebug = false"
        />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useChatStore } from '@/stores/chat'
import { useUserStore } from '@/stores/user'
import { smartChatStream, getChatHistory, submitApproval, trackRecommendClick } from '@/api/chat'
import type { Message } from '@/types'
import AppHeader from '@/components/layout/AppHeader.vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import MessageBubble from '@/components/chat/MessageBubble.vue'
import ChatInput from '@/components/chat/ChatInput.vue'
import WorkflowIndicator from '@/components/chat/WorkflowIndicator.vue'
import HarnessDebugPanel from '@/components/chat/HarnessDebugPanel.vue'
import ToolProgressBar from '@/components/chat/ToolProgressBar.vue'
import QuickActions from '@/components/chat/QuickActions.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { normalizeVideos, resolveVideoId, rememberUrlVideoId } from '@/utils/videos'
import { useChatStream } from '@/composables/useChatStream'

const chatStore = useChatStore()
const userStore = useUserStore()
const route = useRoute()
const { messages, currentSessionId } = storeToRefs(chatStore)
const isDev = import.meta.env.DEV

const messagesContainer = ref<HTMLElement>()
const pendingImages = ref<string[]>([])
const showWorkflow = ref(false)
const {
  workflowStage,
  workflowLabel,
  workflowRoute,
  harnessLiveEvents,
  pendingApproval,
  activeTools,
  resetStreamUi,
  clearPendingApproval,
  applyStreamEvent,
} = useChatStream()
const showHarnessDebug = ref(false)
// 当前上下文视频（来自 URL ?video=<id>，如从 ViewHub 播放页带参跳入）。
// 用户问「这个视频讲了什么」时即使不手动贴 ID 也能路由到视频内回答。
const currentVideoId = ref<string>('')

const approvalMessage = computed(() => {
  const a = pendingApproval.value
  if (!a) return ''
  const preview = a.arguments_preview ? `\n参数：${a.arguments_preview}` : ''
  return `助手想调用「${a.label || a.tool}」${preview}\n\n允许后继续执行（${Math.round(a.timeout_s)}s 内有效）。`
})

async function onApprovalConfirm() {
  const a = pendingApproval.value
  if (!a) return
  try {
    await submitApproval({
      approval_id: a.approval_id,
      decision: 'approve',
      session_id: currentSessionId.value || undefined,
    })
  } catch (e) {
    console.warn('审批失败', e)
  } finally {
    clearPendingApproval()
  }
}

async function onApprovalDeny() {
  const a = pendingApproval.value
  if (!a) return
  try {
    await submitApproval({
      approval_id: a.approval_id,
      decision: 'deny',
      session_id: currentSessionId.value || undefined,
    })
  } catch (e) {
    console.warn('拒绝审批失败', e)
  } finally {
    clearPendingApproval()
  }
}

// 从 Vue Router query 里取 video id：string 直接用，数组取第一个，空则回退 ''
function _videoIdFromQuery(v: unknown): string {
  if (typeof v === 'string') return v
  if (Array.isArray(v) && v.length > 0) return String(v[0])
  return ''
}

// 当前进行中的流式请求控制器（session 切换 / 卸载时 abort，避免浪费 LLM token）
let activeStreamController: AbortController | null = null

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
  // URL query 中的 sessionId（来自 HistoryView 跳转）
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

  // URL query 中的当前视频（?video=<id>，从 ViewHub 播放页带参跳入），
  // 供「这个视频讲了什么」这类问题路由到视频内回答。
  // 数组防抖：?video=a&video=b 时 Vue Router 返回 string[]，取第一个。
  // 只认播放页 URL 带入的 ?video=，不用演示默认 ID 冒充「当前视频」。
  currentVideoId.value = _videoIdFromQuery(route.query.video)
  rememberUrlVideoId(currentVideoId.value)

  window.addEventListener('session-switched', _onSessionSwitched)
})

// 同页从 ?video=A 换成 ?video=B（如 SPA 内切片）时同步 currentVideoId，避免串台
watch(
  () => route.query.video,
  (v) => {
    currentVideoId.value = _videoIdFromQuery(v)
    rememberUrlVideoId(currentVideoId.value)
  },
)

onUnmounted(() => {
  window.removeEventListener('session-switched', _onSessionSwitched)
  activeStreamController?.abort()
})

let historyLoadSeq = 0

async function loadSessionHistory(sessionId: string) {
  if (!userStore.user?.userId) {
    console.warn('[HomeView] loadSessionHistory aborted: no userId')
    return
  }

  const seq = ++historyLoadSeq
  const idsWhenStarted = new Set(messages.value.map((m) => m.id))
  try {
    const history = await getChatHistory(
      sessionId,
      100
    )
    if (seq !== historyLoadSeq || currentSessionId.value !== sessionId) {
      return
    }
    // 同会话里用户已经开聊或 SSE 还在写：不能清掉当前消息再灌库。
    // 跨会话仍靠 seq / sessionId 丢弃过期响应。
    if (messages.value.some((m) => !idsWhenStarted.has(m.id))) {
      return
    }
    if (chatStore.isStreaming && messages.value.some((m) => m.status === 'sending')) {
      return
    }

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
        // DB 存的是 snake_case（video_id），实时流是 camelCase（videoId），统一为 camelCase
        videos: normalizeVideos(msg.videos) || undefined,
        reasons: msg.reasons || undefined,
        citations: msg.citations || undefined,
        // 后端历史接口返回 image_urls（snake_case）
        imageUrls: (msg.image_urls || msg.imageUrls) as any,
      } as any)
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

function handleStopStream() {
  activeStreamController?.abort()
}

async function handleSend(text: string) {
  showWorkflow.value = false

  const imgUrls = [...pendingImages.value]
  pendingImages.value = []

  const videoId = resolveVideoId(text, currentVideoId.value)
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

  await streamAiResponse(text, aiMessageId, videoId, imgUrls)
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
    citations: undefined,
  })

  await streamAiResponse(text, messageId, resolveVideoId(text, currentVideoId.value), imgUrls)
}

// 当前进行中的流式请求控制器（session 切换 / 卸载时 abort，避免浪费 LLM token）
async function streamAiResponse(text: string, aiMessageId: string, extractedVideoId: string | null = null, imgUrls: string[] = []) {
  chatStore.isStreaming = true

  let fullContent = ''
  resetStreamUi()

  const controller = new AbortController()
  activeStreamController = controller

  const batchedUpdateContent = _createBatchedUpdater<Partial<Message>>(
    (next) => chatStore.updateMessage(aiMessageId, next)
  )

  try {
    for await (const event of smartChatStream(text, currentSessionId.value || undefined, extractedVideoId || undefined, userStore.user?.userId, userStore.user?.token, imgUrls.length > 0 ? imgUrls : undefined, controller.signal)) {
      const actionable = applyStreamEvent(event)
      if (!actionable) continue
      if (actionable.type === 'text') {
        fullContent += actionable.content
        batchedUpdateContent({ content: fullContent, status: 'sending' })
      } else if (actionable.type === 'videos') {
        const normVideos = normalizeVideos(actionable.videos)
        chatStore.updateMessage(aiMessageId, {
          videos: normVideos,
          reasons: actionable.reasons || [],
        })
      } else if (actionable.type === 'citations') {
        chatStore.updateMessage(aiMessageId, { citations: actionable.citations })
      }
    }

    chatStore.updateMessage(aiMessageId, {
      content: fullContent,
      status: 'success',
    })
  } catch (error: unknown) {
    // abort 属于主动取消（切 session / 卸载），不显示错误
    if (controller.signal.aborted) {
      chatStore.updateMessage(aiMessageId, {
        content: fullContent.trim() ? fullContent : '已停止生成',
        status: 'error',
      })
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
    resetStreamUi()
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

function handleRebatch() {
  void handleSend('换一批推荐，避开我刚才觉得没用的')
}

async function trackVideoClick(video: { videoId: string }) {
  if (!video?.videoId) return
  try {
    await trackRecommendClick({
      video_id: video.videoId,
      session_id: currentSessionId.value || undefined,
      source: 'video_card',
    })
  } catch (e) {
    console.warn('推荐点击埋点失败', e)
  }
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
  background: linear-gradient(135deg, var(--color-primary-light), var(--color-primary));
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
  box-shadow: 0 4px 16px rgba(74, 108, 247, 0.3);
  animation: welcome-pulse 2.5s ease-in-out infinite;
}

@keyframes welcome-pulse {
  0%, 100% { box-shadow: 0 4px 16px rgba(74, 108, 247, 0.3); }
  50% { box-shadow: 0 4px 24px rgba(74, 108, 247, 0.5); }
}

.welcome-icon {
  font-size: 32px;
}

.empty-state h2 {
  margin: 0 0 8px;
  font-size: 22px;
  color: var(--color-primary-strong);
}

.welcome-text {
  margin: 0 0 24px;
  font-size: 15px;
  color: var(--color-text-secondary);
  line-height: 1.6;
  max-width: 400px;
}

.welcome-text .highlight {
  color: var(--color-primary-light);
  font-weight: 500;
}

.disclaimer-text {
  margin: -12px 0 20px;
  font-size: 12px;
  color: var(--color-text-secondary);
  opacity: 0.85;
  max-width: 420px;
  line-height: 1.5;
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

.harness-debug-btn {
  position: fixed;
  right: 16px;
  bottom: 88px;
  z-index: 100;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  background: var(--color-bg-card);
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}
.harness-debug-btn:hover {
  background: var(--color-primary);
  color: #fff;
}
</style>
