import type { SearchResult, SessionView } from '@/types'

export function sessionsFromContentSearch(
  hits: SearchResult[],
  loaded: SessionView[],
): SessionView[] {
  const loadedMap = new Map(loaded.map((s) => [s.id, s]))
  return hits.map((r) => {
    const existing = loadedMap.get(r.session_id)
    return {
      id: r.session_id,
      title: r.title || existing?.title || '对话',
      createdAt: existing?.createdAt || (r.created_at ? new Date(r.created_at) : new Date()),
      updatedAt: existing?.updatedAt || (r.created_at ? new Date(r.created_at) : new Date()),
      messageCount: existing?.messageCount,
      searchSnippet: r.snippet,
      matched_in: r.matched_in,
    }
  })
}
