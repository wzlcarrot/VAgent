<template>
  <div class="admin-view">
    <AppHeader />
    <main class="admin-main">
      <h1>运维控制台</h1>
      <p class="hint">需配置后端 <code>ADMIN_API_KEY</code>，密钥仅存于本页 sessionStorage。</p>

      <div class="card">
        <label>Admin Key</label>
        <input v-model="adminKey" type="password" placeholder="X-Admin-Key" @change="saveKey" />
      </div>

      <nav class="tabs">
        <button type="button" :class="{ active: tab === 'quality' }" @click="tab = 'quality'; loadQuality">本周质量</button>
        <button type="button" :class="{ active: tab === 'index' }" @click="tab = 'index'">索引</button>
        <button type="button" :class="{ active: tab === 'ops' }" @click="tab = 'ops'; loadOps">熔断/并发</button>
        <button type="button" :class="{ active: tab === 'trace' }" @click="tab = 'trace'; loadTraceSessions">Trace</button>
        <button type="button" :class="{ active: tab === 'golden' }" @click="tab = 'golden'; loadGolden">Weekly Golden</button>
      </nav>

      <template v-if="tab === 'quality'">
        <div class="card actions">
          <button type="button" :disabled="loading" @click="loadQuality">刷新</button>
          <span class="meta" v-if="quality?.week">统计周：{{ quality.week }}</span>
        </div>
        <div class="card" v-if="quality?.metrics">
          <h2>业务质量（7 项）</h2>
          <ul class="metric-list">
            <li><span>今日会话</span><strong>{{ quality.metrics.sessions_today ?? '-' }}</strong></li>
            <li><span>今日消息</span><strong>{{ quality.metrics.messages_today ?? '-' }}</strong></li>
            <li><span>今日活跃用户</span><strong>{{ quality.metrics.active_users_today ?? '-' }}</strong></li>
            <li>
              <span>本周 👍 率</span>
              <strong>{{ formatRate(quality.metrics.feedback_helpful_rate) }}</strong>
              <span class="meta">（{{ quality.metrics.feedback_total_week ?? 0 }} 条反馈）</span>
            </li>
            <li><span>待索引视频</span><strong>{{ quality.metrics.videos_pending ?? '-' }}</strong></li>
            <li><span>近 7 日 citations 覆盖</span><strong>{{ formatRate(quality.metrics.citations_coverage_7d) }}</strong></li>
            <li>
              <span>推荐点击（今日 / 7日）</span>
              <strong>{{ quality.metrics.recommend_clicks_today ?? 0 }} / {{ quality.metrics.recommend_clicks_7d ?? 0 }}</strong>
            </li>
            <li>
              <span>LLM 熔断 / 流式并发</span>
              <strong>{{ quality.metrics.llm_circuit_state }} · {{ quality.metrics.stream_global_active }}/{{ quality.metrics.stream_max_global }}</strong>
            </li>
          </ul>
          <p v-if="quality.index_sla?.indexed_ratio != null" class="meta">
            索引覆盖率 {{ formatRate(quality.index_sla.indexed_ratio) }}
            （{{ quality.metrics.videos_indexed }}/{{ quality.metrics.videos_total }}）
            <span v-if="quality.index_sla.pending_alert" class="alert-badge">pending 告警</span>
          </p>
          <p v-if="quality.index_sla?.pending_sample?.length" class="meta">
            待索引样例：{{ quality.index_sla.pending_sample.join(', ') }}
          </p>
        </div>
      </template>

      <template v-else-if="tab === 'index'">
        <div class="card actions">
          <button type="button" :disabled="loading" @click="loadStats">刷新统计</button>
          <button type="button" :disabled="loading" @click="reindexPending">补索引待处理视频</button>
        </div>

        <div class="card" v-if="stats">
          <h2>索引状态</h2>
          <ul>
            <li>视频总数：{{ stats.videos_total ?? '-' }}</li>
            <li>已索引视频：{{ stats.videos_indexed ?? '-' }}</li>
            <li>向量块数：{{ stats.chunks_total ?? '-' }}</li>
            <li>待索引：{{ stats.videos_pending ?? '-' }}
              <span v-if="stats.pending_alert" class="alert-badge">告警</span>
            </li>
          </ul>
          <p v-if="stats.pending_sample?.length">样例 pending：{{ stats.pending_sample.join(', ') }}</p>
          <p class="meta">联调文档：docs/java-index-callback.md（转码完成必须回调 index-video）</p>
        </div>

        <div class="card">
          <h2>单视频索引</h2>
          <input v-model="videoId" placeholder="video_id" />
          <button type="button" :disabled="loading || !videoId" @click="indexOne">Index Video</button>
          <pre v-if="lastResult">{{ lastResult }}</pre>
        </div>
      </template>

      <template v-else-if="tab === 'ops'">
        <div class="card actions">
          <button type="button" :disabled="loading" @click="loadOps">刷新</button>
        </div>
        <div class="card" v-if="circuit">
          <h2>LLM 熔断</h2>
          <pre>{{ JSON.stringify(circuit, null, 2) }}</pre>
        </div>
        <div class="card" v-if="permits">
          <h2>流式并发许可</h2>
          <pre>{{ JSON.stringify(permits, null, 2) }}</pre>
        </div>
        <div class="card" v-if="compact">
          <h2>Compact 统计</h2>
          <pre>{{ JSON.stringify(compact, null, 2) }}</pre>
        </div>
      </template>

      <template v-else-if="tab === 'trace'">
        <div class="card actions">
          <button type="button" :disabled="loading" @click="loadTraceSessions">刷新最近 Session</button>
        </div>
        <div class="card">
          <h2>按 Session 查询</h2>
          <input v-model="traceSessionId" placeholder="session_id" />
          <button type="button" :disabled="loading || !traceSessionId" @click="loadRuns">加载 Runs</button>
        </div>
        <div class="card" v-if="traceSessions.length">
          <h2>最近 Session</h2>
          <ul class="list">
            <li v-for="s in traceSessions" :key="s.session_id">
              <button type="button" class="linkish" @click="pickSession(s.session_id)">
                {{ s.session_id }}
              </button>
              <span class="meta">runs={{ s.run_count }}</span>
            </li>
          </ul>
        </div>
        <div class="card" v-if="runs.length">
          <h2>Runs · {{ traceSessionId }}</h2>
          <ul class="list">
            <li v-for="r in runs" :key="r.run_id">
              <button type="button" class="linkish" @click="loadSummary(r.run_id)">
                {{ r.run_id }}
              </button>
              <span class="meta">{{ r.status }} · events={{ r.event_count }}</span>
            </li>
          </ul>
        </div>
        <div class="card" v-if="traceSummary">
          <h2>Trace 摘要 · {{ traceSummary.run_id }}</h2>
          <div class="trace-meta">
            <span class="badge" :class="traceSummary.status">{{ traceSummary.status }}</span>
            <span v-if="traceSummary.duration_ms != null">{{ Math.round(Number(traceSummary.duration_ms)) }} ms</span>
            <span v-if="traceSummary.stop_reason">winner: {{ traceSummary.stop_reason }}</span>
          </div>
          <p v-if="traceQuestion" class="trace-q">Q: {{ traceQuestion }}</p>
          <div class="timeline">
            <div v-if="traceTools.length" class="tl-section">
              <h3>Tools ({{ traceTools.length }})</h3>
              <div v-for="(t, i) in traceTools" :key="'t'+i" class="tl-item">
                <span class="tl-type">{{ t.type }}</span>
                <span>{{ t.tool || t.agent || '-' }}</span>
                <span class="meta" v-if="t.latency_ms">{{ t.latency_ms }}ms</span>
              </div>
            </div>
            <div v-if="traceRetries.length" class="tl-section">
              <h3>LLM Retries ({{ traceRetries.length }})</h3>
              <div v-for="(r, i) in traceRetries" :key="'r'+i" class="tl-item warn">
                {{ r.op || 'LLM' }} · attempt {{ r.next_attempt }}/{{ r.max_attempts }}
                <span v-if="r.wait_s"> wait {{ r.wait_s }}s</span>
              </div>
            </div>
            <div v-if="traceGuardrails.length" class="tl-section">
              <h3>Guardrails ({{ traceGuardrails.length }})</h3>
              <div v-for="(g, i) in traceGuardrails" :key="'g'+i" class="tl-item">
                {{ g.stage }} / {{ g.action }} · {{ g.reason }}
              </div>
            </div>
          </div>
          <details class="raw-json">
            <summary>原始 JSON</summary>
            <pre>{{ JSON.stringify(traceSummary, null, 2) }}</pre>
          </details>
        </div>
      </template>

      <template v-else-if="tab === 'golden'">
        <div class="card actions">
          <button type="button" :disabled="loading" @click="loadGolden">刷新</button>
          <select v-model="goldenWeek" @change="loadGolden">
            <option value="">本周</option>
            <option v-for="w in goldenWeeks" :key="w" :value="w">{{ w }}</option>
          </select>
        </div>
        <div class="card" v-if="golden">
          <h2>Weekly Golden · {{ golden.week }}</h2>
          <p>总数 {{ golden.count }}（负 {{ golden.negative }} / 正 {{ golden.positive }}）</p>
          <pre>{{ JSON.stringify(golden.cases?.slice(-20) || [], null, 2) }}</pre>
        </div>
      </template>

      <p v-if="error" class="error">{{ error }}</p>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import {
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

const adminKey = ref(sessionStorage.getItem('vagent_admin_key') || '')
const tab = ref<'quality' | 'index' | 'ops' | 'trace' | 'golden'>('quality')
const stats = ref<Record<string, any> | null>(null)
const quality = ref<Record<string, any> | null>(null)
const videoId = ref('')
const lastResult = ref('')
const error = ref('')
const loading = ref(false)

const circuit = ref<Record<string, unknown> | null>(null)
const permits = ref<Record<string, unknown> | null>(null)
const compact = ref<Record<string, unknown> | null>(null)

const traceSessionId = ref('')
const traceSessions = ref<Array<{ session_id: string; run_count: number; mtime: number }>>([])
const runs = ref<Array<{ run_id: string; started_at?: number; status: string; event_count: number }>>([])
const traceSummary = ref<Record<string, unknown> | null>(null)

const traceQuestion = computed(() => {
  const m = traceSummary.value?.meta as Record<string, unknown> | undefined
  return typeof m?.question === 'string' ? m.question : ''
})
const traceTools = computed(() => {
  const arr = traceSummary.value?.tool_events
  return Array.isArray(arr) ? arr as Array<Record<string, unknown>> : []
})
const traceRetries = computed(() => {
  const arr = traceSummary.value?.llm_retries
  return Array.isArray(arr) ? arr as Array<Record<string, unknown>> : []
})
const traceGuardrails = computed(() => {
  const arr = traceSummary.value?.guardrails
  return Array.isArray(arr) ? arr as Array<Record<string, unknown>> : []
})

const golden = ref<Record<string, any> | null>(null)
const goldenWeek = ref('')
const goldenWeeks = ref<string[]>([])

function saveKey() {
  sessionStorage.setItem('vagent_admin_key', adminKey.value)
}

function formatRate(v: unknown): string {
  if (v == null || v === '') return '-'
  const n = Number(v)
  if (Number.isNaN(n)) return '-'
  return `${(n * 100).toFixed(1)}%`
}

async function loadQuality() {
  loading.value = true
  error.value = ''
  try {
    quality.value = await fetchBusinessQuality(adminKey.value)
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载质量看板失败'
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  loading.value = true
  error.value = ''
  try {
    stats.value = await fetchIndexStats(adminKey.value)
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadOps() {
  loading.value = true
  error.value = ''
  try {
    ;[circuit.value, permits.value, compact.value] = await Promise.all([
      fetchLlmCircuit(adminKey.value),
      fetchStreamPermits(adminKey.value),
      fetchCompactStats(adminKey.value),
    ])
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载运维面板失败'
  } finally {
    loading.value = false
  }
}

async function loadTraceSessions() {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchTraceSessions(adminKey.value)
    traceSessions.value = data.sessions || []
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载 Trace sessions 失败'
  } finally {
    loading.value = false
  }
}

async function pickSession(sid: string) {
  traceSessionId.value = sid
  await loadRuns()
}

async function loadRuns() {
  loading.value = true
  error.value = ''
  traceSummary.value = null
  try {
    const data = await fetchSessionRuns(adminKey.value, traceSessionId.value)
    runs.value = data.runs || []
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载 runs 失败'
  } finally {
    loading.value = false
  }
}

async function loadSummary(runId: string) {
  loading.value = true
  error.value = ''
  try {
    traceSummary.value = await fetchTraceSummary(adminKey.value, traceSessionId.value, runId)
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载摘要失败'
  } finally {
    loading.value = false
  }
}

async function loadGolden() {
  loading.value = true
  error.value = ''
  try {
    golden.value = await fetchWeeklyGolden(adminKey.value, goldenWeek.value)
    goldenWeeks.value = golden.value?.weeks || []
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载 weekly golden 失败'
  } finally {
    loading.value = false
  }
}

async function reindexPending() {
  loading.value = true
  error.value = ''
  try {
    lastResult.value = JSON.stringify(await reindexPendingVideos(adminKey.value, 20), null, 2)
    await loadStats()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '补索引失败'
  } finally {
    loading.value = false
  }
}

async function indexOne() {
  loading.value = true
  error.value = ''
  try {
    lastResult.value = JSON.stringify(await indexVideo(videoId.value, adminKey.value), null, 2)
    await loadStats()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '索引失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (adminKey.value) loadQuality()
})
</script>

<style scoped>
.admin-main {
  max-width: 860px;
  margin: 0 auto;
  padding: 24px;
}
.hint { color: var(--color-text-secondary, #666); font-size: 14px; }
.card {
  background: var(--color-surface, #fff);
  border: 1px solid var(--color-border, #eee);
  border-radius: 12px;
  padding: 16px;
  margin: 16px 0;
}
.tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
.tabs button {
  padding: 6px 12px;
  border: 1px solid var(--color-border, #ddd);
  background: #fafafa;
  border-radius: 8px;
  cursor: pointer;
}
.tabs button.active {
  background: #1a1a1a;
  color: #fff;
  border-color: #1a1a1a;
}
.actions { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
input, select { width: 100%; padding: 8px; margin: 8px 0; }
.actions input, .actions select { width: auto; min-width: 160px; margin: 0; }
button { padding: 8px 16px; cursor: pointer; }
.linkish {
  background: none;
  border: none;
  color: #0b57d0;
  padding: 0;
  text-align: left;
  font-family: ui-monospace, monospace;
  font-size: 13px;
}
.list { list-style: none; padding: 0; margin: 0; }
.list li { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0; border-bottom: 1px solid #f0f0f0; }
.meta { color: #888; font-size: 12px; }
.error { color: #c0392b; }
pre { font-size: 12px; overflow: auto; max-height: 420px; }
.trace-meta { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin: 8px 0; font-size: 13px; }
.badge { padding: 2px 8px; border-radius: 6px; font-size: 12px; background: #eee; }
.badge.completed { background: #d4edda; color: #155724; }
.badge.error, .badge.blocked { background: #f8d7da; color: #721c24; }
.trace-q { font-size: 13px; color: #444; margin: 8px 0; }
.timeline { margin-top: 12px; }
.tl-section { margin-bottom: 16px; }
.tl-section h3 { font-size: 14px; margin: 0 0 8px; }
.tl-item { font-size: 13px; padding: 6px 0; border-bottom: 1px solid #f0f0f0; display: flex; gap: 8px; flex-wrap: wrap; }
.tl-item.warn { color: #b45309; }
.tl-type { font-family: ui-monospace, monospace; color: #666; min-width: 100px; }
.raw-json { margin-top: 12px; font-size: 13px; }
.raw-json summary { cursor: pointer; color: #0b57d0; }
.metric-list { list-style: none; padding: 0; margin: 0; }
.metric-list li {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  padding: 10px 0;
  border-bottom: 1px solid #f0f0f0;
  font-size: 14px;
}
.metric-list li span:first-child { flex: 1; color: #555; min-width: 140px; }
.metric-list li strong { font-size: 16px; color: #111; }
.alert-badge {
  display: inline-block;
  margin-left: 8px;
  padding: 1px 8px;
  border-radius: 6px;
  background: #f8d7da;
  color: #721c24;
  font-size: 12px;
  font-weight: 600;
}
</style>
