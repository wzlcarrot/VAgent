// API Types

export interface ChatResult {
  source: 'java' | 'python'
  data: ChatResponse
  fallback?: {
    from: string
    to: string
    error: string
  }
}

export interface ChatResponse {
  answer: string
  videos?: VideoInfo[]
  workflow_type?: 'video_qa' | 'recommend' | 'chat'
}

export interface VideoInfo {
  videoId: string
  title: string
  cover?: string
  author?: string
  duration?: string
  views?: string
  tags?: string[]
  likeCount?: number
  collectCount?: number
}

export interface VideoQAResponse {
  answer: string
  video: VideoInfo
  key_points?: string[]
  summary?: string
}

export interface RecommendResponse {
  answer: string
  videos: VideoInfo[]
  reasons: Record<string, string>
}

export interface FallbackLog {
  id: string
  timestamp: string
  question: string
  source: 'java' | 'python'
  fallback?: {
    from: string
    to: string
    error: string
  }
  success: boolean
  responseTime?: number
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  status: 'sending' | 'success' | 'error'
  source?: 'java' | 'python'
  videos?: VideoInfo[]
  imageUrls?: string[]
}

export interface ChatSession {
  id: string
  title: string
  messages: Message[]
  createdAt: Date
  updatedAt: Date
}

export interface DbSession {
  session_id: string
  user_id: string
  first_message_at: string
  message_count: number
  first_question: string
}

// 前端 UI 层用的 session 视图模型
export interface SessionView {
  id: string
  title: string
  createdAt: Date
  updatedAt: Date
  messageCount?: number
  matched_in?: 'question' | 'answer'
  searchSnippet?: string
}

export interface SearchResult {
  session_id: string
  title: string
  snippet: string
  matched_in: 'question' | 'answer'
  created_at: string
}

export interface QuickAction {
  icon: string
  label: string
  prompt: string
  keywords?: string[]
}
