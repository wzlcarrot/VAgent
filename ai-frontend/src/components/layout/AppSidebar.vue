<template>
  <aside class="sidebar">
    <div class="sidebar-header">
      <button class="new-chat-btn" @click="handleNewChat">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19"></line>
          <line x1="5" y1="12" x2="19" y2="12"></line>
        </svg>
        <span>新建对话</span>
      </button>
    </div>

    <div class="sidebar-content">
      <div class="section-title" v-if="dbSessions.length > 0">历史会话</div>
      <div class="session-list" v-if="dbSessions.length > 0">
        <div
          v-for="session in dbSessions"
          :key="session.id"
          class="session-item"
          :class="{ active: session.id === currentSessionId }"
          @click="handleSelect(session.id)"
        >
          <div class="session-icon">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15a2 2 0 0 1-2 2H5l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
            </svg>
          </div>
          <span class="session-title">{{ session.title }}</span>
          <button class="delete-btn" @click.stop="handleDelete(session.id)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
        <button v-if="hasMore" class="load-more-btn" @click="loadMoreSessions" :disabled="loadingMore">
          {{ loadingMore ? '加载中...' : '加载更多' }}
        </button>
      </div>
      <div class="empty-state" v-else-if="!loadingMore">
        <p>暂无历史会话</p>
      </div>
    </div>

    <div class="sidebar-footer">
      <div class="user-section" v-if="userStore.user">
        <img :src="userStore.user?.avatar || '/default-avatar.png'" alt="avatar" class="user-avatar" />
        <div class="user-info">
          <span class="user-name">{{ userStore.user.nickname }}</span>
          <span class="user-status">在线</span>
        </div>
      </div>
      <button class="logout-btn" @click="handleLogout" v-if="userStore.isLoggedIn">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
          <polyline points="16 17 21 12 16 7"></polyline>
          <line x1="21" y1="12" x2="9" y2="12"></line>
        </svg>
        <span>退出登录</span>
      </button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useUserStore } from '@/stores/user'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { getChatSessions, deleteChatSession } from '@/api/chat'
import { useNotify } from '@/composables/useNotify'
import type { DbSession, SessionView } from '@/types'

const router = useRouter()
const chatStore = useChatStore()
const userStore = useUserStore()
const { currentSessionId } = storeToRefs(chatStore)
const { showToast, showConfirm } = useNotify()

const dbSessions = ref<SessionView[]>([])
const needsRefresh = ref(false)
const loadingMore = ref(false)
const hasMore = ref(false)
const PAGE_SIZE = 50

watch(() => chatStore.needsSidebarRefresh, (val) => {
  if (val) {
    needsRefresh.value = true
    chatStore.needsSidebarRefresh = false
  }
})

function mapDbSessions(loaded: DbSession[]): SessionView[] {
  return loaded.map((s: DbSession) => ({
    id: s.session_id,
    title: s.first_question?.substring(0, 20) || '新对话',
    createdAt: new Date(s.first_message_at),
    updatedAt: new Date(s.first_message_at),
    messageCount: s.message_count
  }))
}

async function loadSessionsFromDB() {
  if (!userStore.user?.userId) {
    return
  }

  try {
    const loaded = await getChatSessions(PAGE_SIZE, 0)
    dbSessions.value = mapDbSessions(loaded)
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
      dbSessions.value = [...dbSessions.value, ...mapDbSessions(loaded)]
    }
    hasMore.value = loaded.length >= PAGE_SIZE
  } catch (error) {
    console.error('Failed to load more sessions:', error)
  } finally {
    loadingMore.value = false
  }
}

watch(needsRefresh, (val) => {
  if (val) {
    loadSessionsFromDB()
    needsRefresh.value = false
  }
})

function handleNewChat() {
  chatStore.createSession()
}

function handleSelect(sessionId: string) {
  // selectSessionFromHistory 会：
  // 1. 清空 messages
  // 2. 设 currentSessionId
  // 3. 触发 session-switched 事件 → HomeView 自动加载历史
  // 4. 设 needsSidebarRefresh = true → 侧边栏自动刷新列表
  chatStore.selectSessionFromHistory(sessionId)
}

async function handleDelete(sessionId: string) {
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
    chatStore.deleteSession(sessionId)
    dbSessions.value = dbSessions.value.filter(s => s.id !== sessionId)
    showToast('对话已删除', 'success')
  } catch (error) {
    console.error('Failed to delete session:', error)
    showToast('删除失败，请重试', 'error')
  }
}

async function handleLogout() {
  const { logout: apiLogout } = await import('@/api/user')
  await apiLogout()  // 清 httpOnly cookie
  userStore.logout()
  chatStore.reset()  // 清空会话状态，避免新用户看到旧用户历史
  router.push('/login')
}

onMounted(() => {
  loadSessionsFromDB()
})
</script>

<style scoped>
.sidebar {
  width: 260px;
  height: 100%;
  background: var(--color-bg-card);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: var(--space-md);
  border-bottom: 1px solid var(--color-border);
}

.new-chat-btn {
  width: 100%;
  padding: var(--space-sm) var(--space-md);
  background: var(--color-primary);
  color: white;
  border: none;
  border-radius: var(--radius-btn);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-sm);
  font-weight: 500;
  transition: all var(--transition-fast);
}

.new-chat-btn:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}

.sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-sm);
}

.section-title {
  font-size: 12px;
  color: var(--color-text-secondary);
  padding: var(--space-xs) var(--space-sm);
  margin-bottom: var(--space-xs);
}

.session-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-item {
  padding: var(--space-sm) var(--space-md);
  border-radius: var(--radius-btn);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  transition: all var(--transition-fast);
}

.session-item:hover {
  background: var(--color-bg);
}

.session-item.active {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.session-icon {
  flex-shrink: 0;
  opacity: 0.6;
}

.session-title {
  flex: 1;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.delete-btn {
  opacity: 0;
  background: transparent;
  border: none;
  color: var(--color-text-secondary);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition-fast);
}

.session-item:hover .delete-btn {
  opacity: 1;
}

.delete-btn:hover {
  color: var(--color-danger);
  background: var(--color-danger-light);
}

.sidebar-footer {
  padding: var(--space-md);
  border-top: 1px solid var(--color-border);
}

.user-section {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin-bottom: var(--space-sm);
}

.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
}

.user-info {
  display: flex;
  flex-direction: column;
}

.user-name {
  font-size: 14px;
  font-weight: 500;
}

.user-status {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.nav-btn,
.logout-btn {
  width: 100%;
  padding: var(--space-sm) var(--space-md);
  background: transparent;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-btn);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-sm);
  font-size: 14px;
  transition: all var(--transition-fast);
}

.nav-btn:hover {
  background: var(--color-primary-light);
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.logout-btn:hover {
  background: var(--color-danger-light);
  border-color: var(--color-danger);
  color: var(--color-danger);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-xl);
  color: var(--color-text-secondary);
  font-size: 14px;
}

.load-more-btn {
  width: 100%;
  padding: var(--space-sm);
  margin-top: var(--space-sm);
  background: transparent;
  color: var(--color-text-secondary);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-btn);
  cursor: pointer;
  font-size: 13px;
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
</style>
