import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Message, ChatSession } from '@/types'

const STORAGE_KEY = 'viewhub_sessions'
const PERSIST_DEBOUNCE_MS = 300 // 流式输出时合并写入

function loadFromStorage(): ChatSession[] {
  const stored = localStorage.getItem(STORAGE_KEY)
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
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions))
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

  function loadUserSessions() {
    sessions.value = loadFromStorage()
    currentSessionId.value = sessions.value[0]?.id || null
    messages.value = sessions.value.find(s => s.id === currentSessionId.value)?.messages || []
  }

  function getCurrentSession(): ChatSession | undefined {
    return sessions.value.find((s) => s.id === currentSessionId.value)
  }

  function createSession(): ChatSession {
    const session: ChatSession = {
      id: crypto.randomUUID(),
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
      id: crypto.randomUUID(),
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

  function deleteSession(sessionId: string) {
    const index = sessions.value.findIndex((s) => s.id === sessionId)
    if (index !== -1) {
      sessions.value.splice(index, 1)
      _flushPersistNow()
      if (currentSessionId.value === sessionId) {
        currentSessionId.value = sessions.value[0]?.id || null
        messages.value = sessions.value[0]?.messages || []
      }
    }
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
    loadUserSessions,
  }
})