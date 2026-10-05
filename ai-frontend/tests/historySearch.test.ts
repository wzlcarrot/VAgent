import { describe, it, expect } from 'vitest'
import { sessionsFromContentSearch } from '@/utils/historySearch'

describe('sessionsFromContentSearch', () => {
  it('未加载页的命中也会出现', () => {
    const hits = [
      { session_id: 's-new', title: '后端命中', snippet: '…关键词…', matched_in: 'question' as const, created_at: '2026-01-01T00:00:00Z' },
    ]
    const loaded = [
      { id: 's-old', title: '已加载', createdAt: new Date(), updatedAt: new Date(), messageCount: 2 },
    ]
    const out = sessionsFromContentSearch(hits, loaded)
    expect(out).toHaveLength(1)
    expect(out[0].id).toBe('s-new')
    expect(out[0].searchSnippet).toBe('…关键词…')
  })
})
