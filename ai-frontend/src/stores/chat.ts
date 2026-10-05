import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Message, ChatSession } from '@/types'

const LEGACY_STORAGE_KEY = 'viewhub_sessions'
const PERSIST_DEBOUNCE_MS = 300 // 流式输出时合并写入

// 按用户分隔。未登录用 anon，避免换账号后仍读到上一用户的共享 key。
let ownerId: string | null = null

function storageKey(userId: string | null = ownerId): string {
  return userId ? `${LEGACY_STORAGE_KEY}:${userId}` : `${LEGACY_STORAGE_KEY}:anon`
}

function discardLegacySharedStore() {
  try {
    localStorage.removeItem(LEGACY_STORAGE_KEY)
  } catch {
    /* 静默 */
  }
}

// 生成 UUID：优先用 crypto.randomUUID（安全上下文），非 HTTPS/IP 直连时降级
function generateId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  // 降级：基于随机数的 v4 风格 UUID
  const bytes = new Uint8Array(16)
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    crypto.getRandomValues(bytes)
  } else {
    for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256)
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40 // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80 // variant
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

function loadFromStorage(): ChatSession[] {
  const stored = localStorage.getItem(storageKey())
  if (stored) {
    try {
      return JSON.parse(stored)
    } catch {
      return []
    }
  }
  return []
}

function saveToStorage(sessions: ChatSession[]) {
  try {
    localStorage.setItem(storageKey(), JSON.stringify(sessions))
  } catch {
    /* localStorage 满或不可用，静默失败 */
  }
}

export const useChatStore = defineStore('chat', () => {
  const sessions = ref<ChatSession[]>([])
  const currentSessionId = ref<string | null>(null)
  const messages = ref<Message[]>([])
  const isLoading = ref(false)
  const isStreaming = ref(false)
  const needsSidebarRefresh = ref(false)

  // 流式输出时去抖 localStorage 写入：避免每 token 都触发 JSON.stringify
  let persistTimer: ReturnType<typeof setTimeout> | null = null
  let dirtyFlag = false

  function _schedulePersist() {
    dirtyFlag = true
    if (persistTimer) return // 已有 pending 的写入
    persistTimer = setTimeout(() => {
      if (dirtyFlag) {
        saveToStorage(sessions.value)
        dirtyFlag = false
      }
      persistTimer = null
    }, PERSIST_DEBOUNCE_MS)
  }

  function _flushPersistNow() {
    if (persistTimer) {
      clearTimeout(persistTimer)
      persistTimer = null
    }
    // 强制立即写入（即使 dirtyFlag=False 也要保存，因为 sessions 列表本身可能变了）
    saveToStorage(sessions.value)
    dirtyFlag = false
  }

  function _persistSession(session: ChatSession | undefined) {
    if (!session) return
    session.messages = [...messages.value]
    session.updatedAt = new Date()
    _schedulePersist()
  }

  function loadUserSessions(userId?: string | null) {
    // 先把当前用户的内存写回自己的 key，再切换，避免 debounce 把上一用户写进新 key
    _flushPersistNow()
    ownerId = userId || null
    discardLegacySharedStore()
    sessions.value = loadFromStorage()
    currentSessionId.value = sessions.value[0]?.id || null
    messages.value = sessions.value.find(s => s.id === currentSessionId.value)?.messages || []
  }

  function getCurrentSession(): ChatSession | undefined {
    return sessions.value.find((s) => s.id === currentSessionId.value)
  }

  function createSession(): ChatSession {
    const session: ChatSession = {
      id: generateId(),
      title: '新对话',
      messages: [],
      createdAt: new Date(),
      updatedAt: new Date(),
    }
    sessions.value.unshift(session)
    currentSessionId.value = session.id
    messages.value = []
    _flushPersistNow()
    // 新建会话：让侧边栏从 DB 重新拉一次，确保 title/createdAt 等后端字段一致
    // （避免与 DB 真实顺序不一致，特别是 chat_history 表里的 first_question）
    needsSidebarRefresh.value = true
    return session
  }

  function selectSession(sessionId: string) {
    const session = sessions.value.find((s) => s.id === sessionId)
    if (session) {
      currentSessionId.value = session.id
      messages.value = session.messages
    }
  }

  function selectSessionFromHistory(sessionId: string) {
    messages.value = []
    currentSessionId.value = sessionId
    needsSidebarRefresh.value = true
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('session-switched', { detail: { sessionId } }))
    }
  }

  function addMessage(message: Omit<Message, 'id' | 'timestamp'>) {
    const newMessage: Message = {
      ...message,
      id: generateId(),
      timestamp: new Date(),
    }
    messages.value.push(newMessage)

    const session = getCurrentSession()
    if (session) {
      session.title = messages.value.length === 1 ? newMessage.content.slice(0, 30) : session.title
    }
    _persistSession(session)
    return newMessage
  }

  function updateMessage(messageId: string, updates: Partial<Message>) {
    const index = messages.value.findIndex((m) => m.id === messageId)
    if (index === -1) return
    const target = messages.value[index]
    Object.assign(target, updates)
    _persistSession(getCurrentSession())
  }

  function finalizeStreaming() {
    _flushPersistNow()
  }

  function clearCurrentSession() {
    messages.value = []
    if (getCurrentSession()) {
      getCurrentSession()!.messages = []
      getCurrentSession()!.updatedAt = new Date()
      _flushPersistNow()
    }
  }

  function setCurrentSessionId(id: string) {
    currentSessionId.value = id
  }

  function clearMessages() {
    messages.value = []
  }

  function reset() {
    // 登出时清空全部会话状态（内存 + localStorage），避免新用户看到旧用户历史
    if (persistTimer) {
      clearTimeout(persistTimer)
      persistTimer = null
    }
    dirtyFlag = false
    sessions.value = []
    currentSessionId.value = null
    messages.value = []
    try {
      localStorage.removeItem(storageKey())
      discardLegacySharedStore()
    } catch {
      /* 静默 */
    }
    ownerId = null
  }

  function deleteSession(sessionId: string) {
    const index = sessions.value.findIndex((s) => s.id === sessionId)
    if (index !== -1) {
      sessions.value.splice(index, 1)
    }
    // 从历史页打开的会话不在本地列表里。只删列表的话，当前 id 还在，
    // 界面被历史接口刷空之后，下一问仍会带上这个 sessionId。
    if (currentSessionId.value === sessionId) {
      const next = sessions.value[0]
      if (next) {
        currentSessionId.value = next.id
        messages.value = [...(next.messages || [])]
      } else {
        currentSessionId.value = null
        messages.value = []
        createSession()
      }
      if (typeof window !== 'undefined' && currentSessionId.value) {
        window.dispatchEvent(new CustomEvent('session-switched', {
          detail: { sessionId: currentSessionId.value },
        }))
      }
    }
    _flushPersistNow()
  }

  return {
    sessions,
    currentSessionId,
    messages,
    isLoading,
    isStreaming,
    needsSidebarRefresh,
    getCurrentSession,
    createSession,
    selectSession,
    selectSessionFromHistory,
    addMessage,
    updateMessage,
    finalizeStreaming,
    clearCurrentSession,
    setCurrentSessionId,
    clearMessages,
    deleteSession,
    reset,
    loadUserSessions,
  }
})