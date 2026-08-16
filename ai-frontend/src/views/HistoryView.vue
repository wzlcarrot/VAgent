<template>
  <div class="history-view">
    <AppHeader />
    <div class="history-content">
      <div class="header-row">
        <h1>历史记录</h1>
        <div class="header-actions">
          <button class="export-all-btn" @click="exportAll" :disabled="exporting">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            {{ exporting ? '导出中...' : '导出全部' }}
          </button>
        </div>
      </div>

      <div class="search-bar">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索对话标题和内容..."
          class="search-input"
        />
        <span class="search-hint" v-if="searching">🔍 搜索中...</span>
        <span class="search-hint type-hint" v-else-if="searchQuery && searchMode === 'content'">🔎 已搜索对话内容</span>
      </div>

      <div class="session-list" v-if="filteredSessions.length > 0">
        <div
          v-for="session in filteredSessions"
          :key="session.id"
          class="session-item"
        >
            <div class="session-info" @click="openSession(session.id)">
            <div class="session-title">
              {{ session.title }}
              <span class="match-tag" v-if="session.matched_in">{{ session.matched_in === 'question' ? '匹配问题' : '匹配回答' }}</span>
            </div>
            <div class="session-meta">
              <span>{{ formatDate(session.updatedAt) }}</span>
              <span>{{ session.messageCount }} 条消息</span>
            </div>
            <div class="search-snippet" v-if="session.searchSnippet">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="8"></circle>
                <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
              </svg>
              {{ session.searchSnippet }}
            </div>
          </div>
          <div class="session-actions">
            <button class="checkpoint-btn" @click.stop="openCheckpoints(session.id)" title="查看工作流 Checkpoints">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="3"></circle>
                <path d="M12 1v6m0 6v6m11-7h-6m-6 0H1"></path>
              </svg>
            </button>
            <div class="export-dropdown">
              <button class="export-btn" @click.stop="toggleExportMenu(session.id)" title="导出">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                  <polyline points="7 10 12 15 17 10"></polyline>
                  <line x1="12" y1="15" x2="12" y2="3"></line>
                </svg>
              </button>
              <div v-if="openExportMenu === session.id" class="export-menu">
                <button @click.stop="exportSession(session, 'txt')">导出为 TXT</button>
                <button @click.stop="exportSession(session, 'json')">导出为 JSON</button>
              </div>
            </div>
            <button class="delete-btn" @click.stop="deleteSession(session.id)">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              </svg>
            </button>
          </div>
        </div>
      </div>

      <button v-if="hasMore && !searchQuery" class="load-more-btn" @click="loadMoreSessions" :disabled="loadingMore">
        {{ loadingMore ? '加载中...' : '加载更多' }}
      </button>

      <div class="empty-state" v-else>
        <template v-if="searchQuery">
          <div class="empty-icon">🔍</div>
          <p v-if="searching">正在搜索对话内容...</p>
          <p v-else-if="searchMode === 'content'">未找到包含"{{ searchQuery }}"的对话内容</p>
          <p v-else>未找到标题包含"{{ searchQuery }}"的对话</p>
        </template>
        <template v-else>
          <div class="empty-icon">💬</div>
          <p>暂无历史对话</p>
          <p class="empty-hint">和 AI 聊天后，记录会出现在这里</p>
        </template>
      </div>

      <div class="back-btn">
        <button @click="router.push('/')">返回首页</button>
      </div>
    </div>

    <CheckpointViewer
      :visible="showCheckpoints"
      :sessionId="checkpointSessionId"
      @close="showCheckpoints = false"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { getChatSessions, getChatHistory, deleteChatSession, searchChatContent } from '@/api/chat'
import CheckpointViewer from '@/components/chat/CheckpointViewer.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import { useNotify } from '@/composables/useNotify'
import type { DbSession, SessionView, SearchResult } from '@/types'

const router = useRouter()
const userStore = useUserStore()
const { showToast, showConfirm } = useNotify()

const dbSessions = ref<SessionView[]>([])
const searchQuery = ref('')
const searchResults = ref<SearchResult[]>([])
const searching = ref(false)
const searchMode = ref<'title' | 'content'>('title')
const openExportMenu = ref<string | null>(null)
const exporting = ref(false)
const showCheckpoints = ref(false)
const checkpointSessionId = ref<string | null>(null)
const hasMore = ref(false)
const loadingMore = ref(false)
const PAGE_SIZE = 50

function openCheckpoints(sessionId: string) {
  checkpointSessionId.value = sessionId
  showCheckpoints.value = true
}

const filteredSessions = computed(() => {
  const q = searchQuery.value.toLowerCase()
  if (!q) return dbSessions.value

  if (searchMode.value === 'content' && searchResults.value.length > 0) {
    const resultIds = new Set(searchResults.value.map(r => r.session_id))
    const resultMap = new Map(searchResults.value.map(r => [r.session_id, r]))

    return dbSessions.value
      .filter(s => resultIds.has(s.id))
      .map(s => ({
        ...s,
        searchSnippet: resultMap.get(s.id)?.snippet || '',
        matched_in: resultMap.get(s.id)?.matched_in,
      }))
  }

  return dbSessions.value.filter(s =>
    s.title.toLowerCase().includes(q)
  )
})

let searchTimer: ReturnType<typeof setTimeout> | null = null
let lastQuery = ''
watch(searchQuery, (val) => {
  if (searchTimer) clearTimeout(searchTimer)
  if (!val) {
    searchResults.value = []
    searchMode.value = 'title'
    return
  }
  searchTimer = setTimeout(async () => {
    lastQuery = val
    const titleMatches = dbSessions.value.some(s =>
      s.title.toLowerCase().includes(val.toLowerCase())
    )
    if (!titleMatches || val.length >= 2) {
      searchMode.value = 'content'
      searching.value = true
      try {
        const results = await searchChatContent(val)
        if (lastQuery === val) searchResults.value = results
      } catch {
        searchResults.value = []
      } finally {
        searching.value = false
      }
    } else {
      searchMode.value = 'title'
      searchResults.value = []
    }
  }, 300)
})

function toggleExportMenu(sessionId: string) {
  openExportMenu.value = openExportMenu.value === sessionId ? null : sessionId
}

function downloadFile(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function formatMessages(messages: { role: string; content: string; timestamp: string }[]): string {
  return messages.map(m => {
    const role = m.role === 'user' ? '👤 用户' : '🤖 AI'
    const time = m.timestamp ? ` (${new Date(m.timestamp).toLocaleString('zh-CN')})` : ''
    return `${role}${time}:\n${m.content}\n`
  }).join('\n---\n\n')
}

async function loadSessionMessages(sessionId: string): Promise<{ role: string; content: string; timestamp: string }[]> {
  if (!userStore.user?.userId) return []
  try {
    return await getChatHistory(sessionId, 200)
  } catch {
    console.warn(`[HistoryView] Failed to load messages for session: ${sessionId}`)
    return []
  }
}

async function exportSession(session: SessionView, format: 'txt' | 'json') {
  openExportMenu.value = null
  const messages = await loadSessionMessages(session.id)
  if (messages.length === 0) {
    showToast('该对话没有消息可导出', 'warning')
    return
  }

  const safeName = (session.title || '对话').replace(/[^a-zA-Z0-9\u4e00-\u9fa5]/g, '_').substring(0, 30)
  const date = new Date(session.updatedAt).toISOString().split('T')[0]

  if (format === 'txt') {
    const header = `ViewHub AI 对话导出\n标题: ${session.title}\n日期: ${date}\n消息数: ${messages.length}\n\n${'='.repeat(50)}\n\n`
    const body = formatMessages(messages)
    downloadFile(header + body, `${safeName}_${date}.txt`, 'text/plain;charset=utf-8')
  } else {
    const json = JSON.stringify({
      title: session.title,
      exportedAt: new Date().toISOString(),
      messageCount: messages.length,
      messages: messages.map(m => ({
        role: m.role,
        content: m.content,
        timestamp: m.timestamp,
      })),
    }, null, 2)
    downloadFile(json, `${safeName}_${date}.json`, 'application/json;charset=utf-8')
  }
}

async function exportAll() {
  if (exporting.value) return
  exporting.value = true
  try {
    const allContent: string[] = []
    let totalMessages = 0

    const sessionPromises = dbSessions.value.map(session => loadSessionMessages(session.id))
    const allMessages = await Promise.all(sessionPromises)

    for (let i = 0; i < dbSessions.value.length; i++) {
      const session = dbSessions.value[i]
      const messages = allMessages[i]
      if (messages.length === 0) continue
      totalMessages += messages.length

      const date = new Date(session.updatedAt).toLocaleString('zh-CN')
      allContent.push(`\n${'='.repeat(60)}`)
      allContent.push(`对话: ${session.title}`)
      allContent.push(`时间: ${date}`)
      allContent.push(`消息: ${messages.length} 条`)
      allContent.push(`${'='.repeat(60)}\n`)
      allContent.push(formatMessages(messages))
    }

    const header = `ViewHub AI 全部对话导出\n导出时间: ${new Date().toLocaleString('zh-CN')}\n对话数: ${dbSessions.value.length}\n总消息数: ${totalMessages}\n\n`
    downloadFile(header + allContent.join('\n'), `ViewHub_全部对话_${new Date().toISOString().split('T')[0]}.txt`, 'text/plain;charset=utf-8')
  } finally {
    exporting.value = false
  }
}

async function loadSessionsFromDB() {
  if (!userStore.user?.userId) {
    return
  }

  try {
    const loaded = await getChatSessions(PAGE_SIZE, 0)
    dbSessions.value = loaded.map((s: DbSession) => ({
      id: s.session_id,
      title: s.first_question?.substring(0, 50) || '新对话',
      createdAt: new Date(s.first_message_at),
      updatedAt: new Date(s.first_message_at),
      messageCount: s.message_count
    }))
    hasMore.value = loaded.length >= PAGE_SIZE
  } catch (error) {
    console.error('Failed to load sessions:', error)
  }
}

async function loadMoreSessions() {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  try {
    const loaded = await getChatSessions(PAGE_SIZE, dbSessions.value.length)
    if (loaded.length > 0) {
      const mapped = loaded.map((s: DbSession) => ({
        id: s.session_id,
        title: s.first_question?.substring(0, 50) || '新对话',
        createdAt: new Date(s.first_message_at),
        updatedAt: new Date(s.first_message_at),
        messageCount: s.message_count
      }))
      dbSessions.value = [...dbSessions.value, ...mapped]
    }
    hasMore.value = loaded.length >= PAGE_SIZE
  } catch (error) {
    console.error('Failed to load more sessions:', error)
  } finally {
    loadingMore.value = false
  }
}

function formatDate(date: Date): string {
  return new Date(date).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function openSession(sessionId: string) {
  // URL query 是最可靠的跨页面通信方式，不依赖 store 在组件卸载/重挂周期中的状态
  router.push({ path: '/', query: { session: sessionId } })
}

async function deleteSession(sessionId: string) {
  const ok = await showConfirm({
    title: '删除对话',
    message: '确定删除这条对话？此操作无法撤销。',
    confirmText: '删除',
    variant: 'danger',
  })
  if (!ok) return
  if (!userStore.user?.userId) return

  try {
    await deleteChatSession(sessionId)
    dbSessions.value = dbSessions.value.filter(s => s.id !== sessionId)
    showToast('对话已删除', 'success')
  } catch (error) {
    console.error('Failed to delete session:', error)
    showToast('删除失败，请重试', 'error')
  }
}

function onClickOutside(e: MouseEvent) {
  if (openExportMenu.value) {
    const target = e.target as HTMLElement
    if (!target.closest('.export-dropdown')) {
      openExportMenu.value = null
    }
  }
}

onMounted(() => {
  loadSessionsFromDB()
  document.addEventListener('click', onClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', onClickOutside)
})
</script>

<style scoped>
.history-view {
  min-height: 100vh;
  background: var(--color-bg);
}

.history-content {
  max-width: 800px;
  margin: 0 auto;
  padding: var(--space-xl);
}

.header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-lg);
}

.header-row h1 {
  font-size: 24px;
  font-weight: 600;
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.export-all-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: var(--color-primary);
  color: #fff;
  border: none;
  border-radius: var(--radius-btn);
  font-size: 13px;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.export-all-btn:hover:not(:disabled) {
  opacity: 0.9;
}

.export-all-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.search-bar {
  margin-bottom: var(--space-lg);
  display: flex;
  align-items: center;
  gap: 8px;
}

.search-input {
  flex: 1;
  padding: var(--space-sm) var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-btn);
  font-size: 14px;
  background: var(--color-bg-card);
}

.search-input:focus {
  outline: none;
  border-color: var(--color-primary);
}

.search-hint {
  font-size: 12px;
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.search-hint.type-hint {
  color: var(--color-primary);
}

.session-list {
  background: var(--color-bg-card);
  border-radius: var(--radius-card);
  overflow: hidden;
}

.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-md);
  border-bottom: 1px solid var(--color-border);
  transition: background var(--transition-fast);
}

.session-item:last-child {
  border-bottom: none;
}

.session-item:hover {
  background: var(--color-bg);
}

.session-info {
  flex: 1;
  cursor: pointer;
}

.session-title {
  font-size: 14px;
  font-weight: 500;
  margin-bottom: var(--space-xs);
  display: flex;
  align-items: center;
  gap: 8px;
}

.match-tag {
  font-size: 10px;
  background: var(--color-primary);
  color: #fff;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 400;
}

.search-snippet {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-top: 6px;
  display: flex;
  align-items: flex-start;
  gap: 4px;
  line-height: 1.5;
  background: var(--color-bg-card);
  padding: 6px 8px;
  border-radius: 6px;
}

.session-meta {
  display: flex;
  gap: var(--space-md);
  font-size: 12px;
  color: var(--color-text-secondary);
}

.session-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.export-dropdown {
  position: relative;
}

.export-btn {
  padding: var(--space-sm);
  color: var(--color-text-secondary);
  background: none;
  border: none;
  border-radius: var(--radius-btn);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.export-btn:hover {
  background: var(--color-bg);
  color: var(--color-primary);
}

.export-menu {
  position: absolute;
  right: 0;
  top: 100%;
  z-index: 10;
  background: #fff;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  overflow: hidden;
  min-width: 140px;
}

.export-menu button {
  display: block;
  width: 100%;
  padding: 8px 16px;
  background: none;
  border: none;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.export-menu button:hover {
  background: var(--color-bg);
  color: var(--color-primary);
}

.delete-btn {
  padding: var(--space-sm);
  color: var(--color-text-secondary);
  background: none;
  border: none;
  border-radius: var(--radius-btn);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.delete-btn:hover {
  background: var(--color-danger-bg);
  color: var(--color-danger);
}

.checkpoint-btn {
  padding: var(--space-sm);
  color: var(--color-text-secondary);
  background: none;
  border: none;
  border-radius: var(--radius-btn);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.checkpoint-btn:hover {
  background: var(--color-primary-bg);
  color: var(--color-primary-strong);
}

.empty-state {
  text-align: center;
  padding: var(--space-2xl);
  color: var(--color-text-secondary);
}

.load-more-btn {
  display: block;
  width: 100%;
  padding: var(--space-sm);
  margin-top: var(--space-md);
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-btn);
  cursor: pointer;
  font-size: 14px;
  transition: all var(--transition-fast);
}

.load-more-btn:hover:not(:disabled) {
  color: var(--color-primary);
  border-color: var(--color-primary);
}

.load-more-btn:disabled {
  opacity: 0.6;
  cursor: default;
}

.back-btn {
  margin-top: var(--space-xl);
}

.back-btn button {
  padding: var(--space-sm) var(--space-lg);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-btn);
  font-size: 14px;
  transition: all var(--transition-fast);
}

.back-btn button:hover {
  background: var(--color-bg);
}
</style>
