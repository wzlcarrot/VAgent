<template>
  <div class="message-bubble" :class="[`role-${message.role}`, `status-${message.status}`]">
    <div class="avatar" v-if="message.role === 'assistant'">
      <span class="avatar-icon">🤖</span>
    </div>
    <div class="bubble-content">
      <div class="bubble-main" v-html="renderedContent"></div>

      <div class="image-grid" v-if="message.imageUrls && message.imageUrls.length > 0">
        <div class="image-item" v-for="url in message.imageUrls" :key="url">
          <img :src="url" alt="用户图片" class="chat-image" @click="previewImage(url)" />
        </div>
      </div>
      
      <!--
        视频链接卡片：从 AI 文本里正则提取的 URL。
        如果 message.videos 已经有视频推荐（HomeView 的 videoCards 已渲染），
        则不再渲染 videoLinks，避免正则误匹配 winner_text 里的"视频"字产生重复卡片。
      -->
      <div class="video-cards" v-if="videoLinks.length > 0 && !(message.videos && message.videos.length > 0)">
        <a 
          v-for="link in videoLinks" 
          :key="link.url"
          :href="link.url"
          target="_blank"
          rel="noopener noreferrer"
          class="video-card"
        >
          <div class="video-thumbnail">
            <img v-if="link.thumbnail" :src="link.thumbnail" :alt="link.title" />
            <div v-else class="thumbnail-placeholder">🎬</div>
          </div>
          <div class="video-info">
            <div class="video-title">{{ link.title }}</div>
            <div class="video-desc" v-if="link.description">{{ link.description }}</div>
            <div class="video-link-text">点击查看视频 →</div>
          </div>
        </a>
      </div>
      
      <div class="bubble-meta">
        <span class="source-tag" v-if="message.source">{{ message.source.toUpperCase() }}</span>
        <span class="time">{{ formatTime(message.timestamp) }}</span>
        <button v-if="message.status === 'error'" class="retry-btn" @click="handleRetry" title="重新发送" aria-label="重新发送">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="23 4 23 10 17 10"></polyline>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
          </svg>
        </button>
        <button class="copy-btn" :class="{ copied }" @click="copyContent" :title="copied ? '已复制' : '复制'" :aria-label="copied ? '已复制' : '复制'">
          <svg v-if="!copied" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
          </svg>
          <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
        </button>
        <div
          v-if="message.role === 'assistant' && message.status === 'success' && sessionId && !isStreaming"
          class="feedback-btns"
        >
          <button
            class="feedback-btn"
            :class="{ active: feedbackState === 'helpful' }"
            :disabled="feedbackState !== ''"
            title="有用"
            aria-label="有用"
            @click="sendFeedback('helpful')"
          >
            有用
          </button>
          <button
            class="feedback-btn"
            :class="{ active: feedbackState === 'not_helpful' }"
            :disabled="feedbackState !== ''"
            title="没用"
            aria-label="没用"
            @click="sendFeedback('not_helpful')"
          >
            没用
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onBeforeUnmount } from 'vue'
import { renderMarkdown } from '@/utils/markdown'
import { submitFeedback } from '@/api/chat'
import type { Message } from '@/types'

const props = defineProps<{
  message: Message
  sessionId?: string
  messageIndex?: number
  isStreaming?: boolean
}>()

const emit = defineEmits<{
  retry: [messageId: string]
}>()

const copied = ref(false)
const feedbackState = ref<'helpful' | 'not_helpful' | ''>('')
let copyTimer: ReturnType<typeof setTimeout> | null = null

onBeforeUnmount(() => {
  if (copyTimer) clearTimeout(copyTimer)
})

async function sendFeedback(kind: 'helpful' | 'not_helpful') {
  if (!props.sessionId || feedbackState.value || props.isStreaming) return
  feedbackState.value = kind
  const videoIds = (props.message.videos || []).map(v => v.videoId).filter(Boolean)
  try {
    await submitFeedback({
      session_id: props.sessionId,
      message_index: props.messageIndex ?? 0,
      feedback: kind,
      video_ids: videoIds,
    })
  } catch (e) {
    console.warn('提交反馈失败:', e)
    feedbackState.value = ''
  }
}

function handleRetry() {
  emit('retry', props.message.id)
}

interface VideoLink {
  url: string
  title: string
  description?: string
  thumbnail?: string
}

const videoLinks = computed<VideoLink[]>(() => {
  const content = props.message.content
  const links: VideoLink[] = []

  const urlPattern = /(?:Video|视频)链接[：:]\s*\[([^\]]+)\]\(([^)]+)\)|(?:Video|视频)[：:]\s*([^\s]+)|\[([^\]]+)\]\(([^)]+\.(?:mp4|webm|mov|avi))\)/gi

  for (const match of content.matchAll(urlPattern)) {
    if (match[1] && match[2]) {
      links.push({
        title: match[1],
        url: match[2],
      })
    } else if (match[3]) {
      links.push({
        title: '相关视频',
        url: match[3],
      })
    } else if (match[4] && match[5]) {
      links.push({
        title: match[4],
        url: match[5],
      })
    }
  }

  const simpleUrlPattern = /(https?:\/\/[^\s]+(?:mp4|webm|mov|avi)[^\s]*)/gi
  for (const match of content.matchAll(simpleUrlPattern)) {
    if (!links.some(l => l.url === match[1])) {
      links.push({
        title: '视频链接',
        url: match[1],
      })
    }
  }

  return links
})

const renderedContent = computed(() => {
  let content = props.message.content
  // 过滤 MiniMax-M3 推理模型痕迹
  content = content.replace(/<think>[\s\S]*?<\/think>/g, '')
  // 过滤历史脏数据：recommend workflow 之前会拼一段"为你推荐以下视频：..."文本
  // 现在改用 videos 事件直接给视频卡了，但 DB 里的旧记录还有这段文字
  // 有 videos 时整段隐藏（视频卡已经包含视频名+理由）
  if (props.message.videos && props.message.videos.length > 0) {
    if (/^(根据你的喜好[，,]?\s*)?为你推荐(以下)?视频[：:]?/i.test(content.trim())) {
      return ''
    }
  }
  content = content.replace(/\[([^\]]+)\]\(([^)]+\.(?:mp4|webm|mov|avi))\)/gi, '<a href="$2" target="_blank" class="video-link">[$1]</a>')
  return renderMarkdown(content)
})

function formatTime(date: Date): string {
  const d = new Date(date)
  const now = new Date()
  const isToday = d.toDateString() === now.toDateString()
  if (isToday) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit'
  })
}

async function copyContent() {
  const text = props.message.content
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      if (!ok) throw new Error('execCommand 失败')
    }
    copied.value = true
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => { copied.value = false }, 1500)
  } catch (e) {
    console.warn('复制失败:', e)
  }
}

function previewImage(url: string) {
  window.open(url, '_blank', 'noopener,noreferrer')
}
</script>

<style scoped>
.message-bubble {
  display: flex;
  gap: var(--space-sm);
  margin-bottom: var(--space-md);
  animation: fadeIn 0.3s ease-out;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.role-user {
  flex-direction: row-reverse;
}

.avatar {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-full);
  background: var(--color-bg);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.avatar-icon {
  font-size: 16px;
}

.bubble-content {
  max-width: 70%;
  min-width: 80px;
}

.bubble-main {
  padding: var(--space-md);
  border-radius: var(--radius-bubble);
  line-height: 1.6;
}

.role-user .bubble-main {
  background: var(--color-user-bubble);
  color: white;
  border-bottom-right-radius: 4px;
}

.role-assistant .bubble-main {
  background: var(--color-ai-bubble);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-bottom-left-radius: 4px;
  box-shadow: var(--shadow-sm);
}

.status-sending .bubble-main {
  opacity: 0.7;
}

.status-error .bubble-main {
  border: 2px solid var(--color-danger);
}

.bubble-meta {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin-top: var(--space-xs);
  font-size: 12px;
  color: var(--color-text-secondary);
}

.role-user .bubble-meta {
  justify-content: flex-end;
}

.source-tag {
  background: var(--color-primary);
  color: white;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
}

.feedback-btns {
  display: flex;
  gap: 2px;
}

.feedback-btn {
  padding: 4px 6px;
  border-radius: 4px;
  color: var(--color-text-secondary);
  background: none;
  border: none;
  cursor: pointer;
  transition: all var(--transition-fast);
  opacity: 1;
}

.message-bubble:hover .feedback-btn {
  opacity: 1;
}

.feedback-btn:hover:not(:disabled) {
  background: var(--color-bg);
}

.feedback-btn.active {
  opacity: 1;
}

.feedback-btn.active[title="有用"],
.feedback-btn[title="有用"]:hover:not(:disabled) {
  color: var(--color-success);
}

.feedback-btn.active[title="没用"],
.feedback-btn[title="没用"]:hover:not(:disabled) {
  color: var(--color-danger);
}

.feedback-btn:disabled {
  cursor: default;
}

.copy-btn {
  padding: 4px;
  border-radius: 4px;
  color: var(--color-text-secondary);
  background: none;
  border: none;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.copy-btn:hover {
  background: var(--color-bg);
  color: var(--color-text);
}
.copy-btn.copied {
  color: var(--color-success);
}

.retry-btn {
  padding: 4px;
  border-radius: 4px;
  color: var(--color-text-secondary);
  background: none;
  border: none;
  cursor: pointer;
  transition: all var(--transition-fast);
  opacity: 0;
}

.message-bubble:hover .retry-btn {
  opacity: 1;
}

.retry-btn:hover {
  background: var(--color-danger-bg);
  color: var(--color-danger);
}

.image-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.image-item {
  width: 120px;
  height: 90px;
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  border: 1px solid var(--color-border);
  transition: transform 0.2s;
}

.image-item:hover {
  transform: scale(1.03);
}

.chat-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.video-cards {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  margin-top: var(--space-md);
}

.video-card {
  display: flex;
  gap: var(--space-md);
  padding: var(--space-md);
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  text-decoration: none;
  color: inherit;
  transition: all 0.3s ease;
}

.video-card:hover {
  border-color: var(--color-primary);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.video-thumbnail {
  width: 120px;
  height: 68px;
  border-radius: var(--radius-btn);
  overflow: hidden;
  background: var(--color-bg-card);
  flex-shrink: 0;
}

.video-thumbnail img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.thumbnail-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.video-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
}

.video-title {
  font-weight: 500;
  color: var(--color-text);
  margin-bottom: var(--space-xs);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.video-desc {
  font-size: 13px;
  color: var(--color-text-secondary);
  margin-bottom: var(--space-xs);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.video-link-text {
  font-size: 12px;
  color: var(--color-primary);
  font-weight: 500;
}

/* Markdown 样式 */
.bubble-main h1, .bubble-main h2, .bubble-main h3,
.bubble-main h4, .bubble-main h5, .bubble-main h6 {
  margin-top: 16px;
  margin-bottom: 8px;
  font-weight: 600;
  line-height: 1.3;
}

.bubble-main h1 { font-size: 1.5em; }
.bubble-main h2 { font-size: 1.3em; }
.bubble-main h3 { font-size: 1.1em; }

.bubble-main p {
  margin: 0.5em 0;
}

.bubble-main ul, .bubble-main ol {
  margin: 0.5em 0;
  padding-left: 1.5em;
}

.bubble-main li {
  margin: 0.25em 0;
}

.bubble-main blockquote {
  margin: 0.5em 0;
  padding: 0.5em 1em;
  border-left: 4px solid var(--color-primary);
  background: var(--color-bg);
  border-radius: 0 var(--radius-btn) var(--radius-btn) 0;
  color: var(--color-text-secondary);
}

.bubble-main pre {
  margin: 0.75em 0;
  padding: 0.75em;
  background: var(--color-code-bg);
  border-radius: var(--radius-btn);
  overflow-x: auto;
}

.bubble-main code {
  font-family: 'Fira Code', 'Monaco', 'Consolas', monospace;
  font-size: 0.9em;
}

.bubble-main :not(pre) > code {
  padding: 0.2em 0.4em;
  background: var(--color-bg);
  border-radius: 4px;
  color: var(--color-primary);
}

.bubble-main table {
  width: 100%;
  margin: 0.75em 0;
  border-collapse: collapse;
}

.bubble-main th, .bubble-main td {
  padding: 0.5em;
  border: 1px solid var(--color-border);
  text-align: left;
}

.bubble-main th {
  background: var(--color-bg);
  font-weight: 600;
}

.bubble-main a {
  color: var(--color-primary);
  text-decoration: none;
}

.bubble-main a:hover {
  text-decoration: underline;
}

.bubble-main hr {
  margin: 1em 0;
  border: none;
  border-top: 1px solid var(--color-border);
}

.bubble-main img {
  max-width: 100%;
  border-radius: var(--radius-btn);
}

.bubble-main .video-link {
  color: var(--color-primary);
  font-weight: 500;
}

@media (max-width: 640px) {
  .video-card {
    flex-direction: column;
  }
  
  .video-thumbnail {
    width: 100%;
    height: 160px;
  }
}
</style>
