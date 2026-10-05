import axios from 'axios'

function adminHeaders(key: string) {
  return { 'X-Admin-Key': key }
}

export async function fetchIndexStats(adminKey: string) {
  const res = await axios.get('/ai/admin/index-stats', { headers: adminHeaders(adminKey) })
  return res.data
}

export async function registerLocalVideo(
  adminKey: string,
  payload: { video_id: string; title: string; tags?: string; introduction?: string; body?: string },
) {
  const res = await axios.post('/ai/admin/register-video', payload, { headers: adminHeaders(adminKey) })
  return res.data
}

export async function indexVideo(videoId: string, adminKey: string) {
  const res = await axios.post(`/ai/admin/index-video/${encodeURIComponent(videoId)}`, null, {
    headers: adminHeaders(adminKey),
  })
  return res.data
}

export async function reindexPendingVideos(adminKey: string, limit = 50) {
  const res = await axios.post(`/ai/admin/reindex-pending?limit=${limit}`, null, {
    headers: adminHeaders(adminKey),
  })
  return res.data
}

export async function fetchAdminFeatures(adminKey: string) {
  const res = await axios.get('/ai/admin/features', { headers: adminHeaders(adminKey) })
  return res.data
}

export async function fetchBusinessQuality(adminKey: string) {
  const res = await axios.get('/ai/admin/business-quality', { headers: adminHeaders(adminKey) })
  return res.data
}

export async function fetchAdminStats(adminKey: string) {
  const res = await axios.get('/ai/admin/stats', { headers: adminHeaders(adminKey) })
  return res.data
}

export async function fetchLlmCircuit(adminKey: string) {
  const res = await axios.get('/ai/admin/llm-circuit', { headers: adminHeaders(adminKey) })
  return res.data
}

export async function fetchStreamPermits(adminKey: string) {
  const res = await axios.get('/ai/admin/stream-permits', { headers: adminHeaders(adminKey) })
  return res.data
}

export async function fetchCompactStats(adminKey: string, sessionId = '') {
  const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''
  const res = await axios.get(`/ai/admin/compact-stats${q}`, { headers: adminHeaders(adminKey) })
  return res.data
}

export async function fetchTraceSessions(adminKey: string, limit = 30) {
  const res = await axios.get(`/ai/admin/trace-sessions?limit=${limit}`, {
    headers: adminHeaders(adminKey),
  })
  return res.data as { sessions: Array<{ session_id: string; run_count: number; mtime: number }> }
}

export async function fetchSessionRuns(adminKey: string, sessionId: string) {
  const res = await axios.get(`/ai/admin/traces/${encodeURIComponent(sessionId)}`, {
    headers: adminHeaders(adminKey),
  })
  return res.data as {
    session_id: string
    runs: Array<{ run_id: string; started_at?: number; status: string; event_count: number }>
  }
}

export async function fetchTraceSummary(adminKey: string, sessionId: string, runId: string) {
  const res = await axios.get(
    `/ai/admin/traces/${encodeURIComponent(sessionId)}/${encodeURIComponent(runId)}`,
    { headers: adminHeaders(adminKey) },
  )
  return res.data
}

export async function fetchWeeklyGolden(adminKey: string, week = '') {
  const q = week ? `?week=${encodeURIComponent(week)}` : ''
  const res = await axios.get(`/ai/admin/weekly-golden${q}`, { headers: adminHeaders(adminKey) })
  return res.data
}
