import { afterEach, describe, expect, it, vi } from 'vitest'
import axios from 'axios'
import {
  fetchAdminStats,
  fetchBusinessQuality,
  fetchCompactStats,
  fetchIndexStats,
  fetchLlmCircuit,
  fetchSessionRuns,
  fetchStreamPermits,
  fetchTraceSessions,
  fetchTraceSummary,
  fetchWeeklyGolden,
  indexVideo,
  reindexPendingVideos,
} from '@/api/admin'

vi.mock('axios')

const get = axios.get as unknown as ReturnType<typeof vi.fn>
const post = axios.post as unknown as ReturnType<typeof vi.fn>
const H = (k: string) => ({ headers: { 'X-Admin-Key': k } })

describe('admin api', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('GET 类接口：URL / 头 / 返回值', async () => {
    get.mockResolvedValue({ data: { ok: 1 } })
    expect(await fetchIndexStats('k')).toEqual({ ok: 1 })
    expect(get).toHaveBeenCalledWith('/ai/admin/index-stats', H('k'))

    expect(await fetchBusinessQuality('k')).toEqual({ ok: 1 })
    expect(get).toHaveBeenCalledWith('/ai/admin/business-quality', H('k'))

    expect(await fetchAdminStats('k')).toEqual({ ok: 1 })
    expect(get).toHaveBeenCalledWith('/ai/admin/stats', H('k'))

    expect(await fetchLlmCircuit('k')).toEqual({ ok: 1 })
    expect(get).toHaveBeenCalledWith('/ai/admin/llm-circuit', H('k'))

    expect(await fetchStreamPermits('k')).toEqual({ ok: 1 })
    expect(get).toHaveBeenCalledWith('/ai/admin/stream-permits', H('k'))
  })

  it('POST 类接口：编码 + limit', async () => {
    post.mockResolvedValue({ data: { ok: true } })
    await indexVideo('a/b c', 'k2')
    expect(post).toHaveBeenCalledWith('/ai/admin/index-video/a%2Fb%20c', null, H('k2'))

    await reindexPendingVideos('k3', 7)
    expect(post).toHaveBeenCalledWith('/ai/admin/reindex-pending?limit=7', null, H('k3'))
  })

  it('compact-stats：session_id 可选', async () => {
    get.mockResolvedValue({ data: {} })
    await fetchCompactStats('k')
    expect(get).toHaveBeenCalledWith('/ai/admin/compact-stats', H('k'))
    await fetchCompactStats('k', 's 1')
    expect(get).toHaveBeenCalledWith('/ai/admin/compact-stats?session_id=s%201', H('k'))
  })

  it('trace 相关：session / run / summary', async () => {
    get.mockResolvedValueOnce({ data: { sessions: [] } })
    expect(await fetchTraceSessions('k', 5)).toEqual({ sessions: [] })
    expect(get).toHaveBeenLastCalledWith('/ai/admin/trace-sessions?limit=5', H('k'))

    get.mockResolvedValueOnce({ data: { runs: [] } })
    await fetchSessionRuns('k', 'sess/1')
    expect(get).toHaveBeenLastCalledWith('/ai/admin/traces/sess%2F1', H('k'))

    get.mockResolvedValueOnce({ data: { run_id: 'r' } })
    await fetchTraceSummary('k', 's/1', 'r/2')
    expect(get).toHaveBeenLastCalledWith('/ai/admin/traces/s%2F1/r%2F2', H('k'))
  })

  it('weekly-golden：week 可选', async () => {
    get.mockResolvedValue({ data: {} })
    await fetchWeeklyGolden('k')
    expect(get).toHaveBeenCalledWith('/ai/admin/weekly-golden', H('k'))
    await fetchWeeklyGolden('k', '2026-W38')
    expect(get).toHaveBeenCalledWith('/ai/admin/weekly-golden?week=2026-W38', H('k'))
  })
})
