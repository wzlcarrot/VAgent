<template>
  <Transition name="harness-panel">
    <div v-if="visible" class="harness-panel" @click.self="onClose">
      <div class="panel-content">
        <div class="panel-header">
          <h3>Harness 调试</h3>
          <button class="close-btn" @click="onClose">×</button>
        </div>

        <div class="tabs">
          <button :class="{ active: tab === 'live' }" @click="tab = 'live'">实时事件</button>
          <button :class="{ active: tab === 'trace' }" @click="tab = 'trace'; loadTraces()">Run Trace</button>
        </div>

        <div v-if="tab === 'live'" class="event-list">
          <div v-if="!events.length" class="empty">发送消息后此处显示 harness 事件</div>
          <div v-for="(ev, i) in events" :key="i" class="event-row">
            <span class="event-type">{{ ev.event }}</span>
            <span class="event-payload">{{ formatPayload(ev.payload) }}</span>
          </div>
        </div>

        <div v-else class="trace-list">
          <div v-if="traceLoading" class="empty">加载中…</div>
          <div v-else-if="!runs.length" class="empty">暂无 trace 记录</div>
          <template v-else>
            <div v-for="run in runs" :key="run.run_id" class="run-block">
              <div class="run-header" @click="toggleRun(run.run_id)">
                <span>{{ run.run_id }}</span>
                <span class="run-meta">{{ run.status }} · {{ run.event_count }} events</span>
              </div>
              <div v-if="expandedRun === run.run_id" class="run-events">
                <div v-for="(ev, j) in runEvents[run.run_id] || []" :key="j" class="event-row small">
                  <span class="seq">#{{ ev.seq }}</span>
                  <span class="event-type">{{ ev.type }}</span>
                  <span class="event-payload">{{ formatPayload(ev.payload) }}</span>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { getSessionTraces, getSessionTrace, type HarnessEvent, type TraceRun } from '@/api/chat'

const props = defineProps<{
  visible: boolean
  sessionId: string | null
  liveEvents: HarnessEvent[]
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const tab = ref<'live' | 'trace'>('live')
const events = ref<HarnessEvent[]>([])
const runs = ref<TraceRun[]>([])
const runEvents = ref<Record<string, Array<{ seq: number; type: string; payload: Record<string, unknown> }>>>({})
const expandedRun = ref<string | null>(null)
const traceLoading = ref(false)

watch(() => props.liveEvents, (v) => { events.value = [...v] }, { deep: true, immediate: true })

async function loadTraces() {
  if (!props.sessionId) return
  traceLoading.value = true
  try {
    const data = await getSessionTraces(props.sessionId)
    runs.value = data.runs || []
  } catch {
    runs.value = []
  } finally {
    traceLoading.value = false
  }
}

async function toggleRun(runId: string) {
  if (expandedRun.value === runId) {
    expandedRun.value = null
    return
  }
  expandedRun.value = runId
  if (!props.sessionId || runEvents.value[runId]) return
  try {
    const data = await getSessionTrace(props.sessionId, runId)
    runEvents.value[runId] = data.events || []
  } catch {
    runEvents.value[runId] = []
  }
}

function formatPayload(p: Record<string, unknown> | undefined): string {
  if (!p) return ''
  return Object.entries(p)
    .filter(([, v]) => v != null && v !== '')
    .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`)
    .join(' · ')
}

function onClose() {
  emit('close')
}

watch(() => props.visible, (v) => {
  if (v && tab.value === 'trace') loadTraces()
})
</script>

<style scoped>
.harness-panel {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: stretch;
  justify-content: flex-end;
  z-index: 210;
}
.panel-content {
  width: 420px;
  max-width: 92vw;
  background: #fff;
  display: flex;
  flex-direction: column;
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.15);
}
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  border-bottom: 1px solid #eee;
}
.panel-header h3 { margin: 0; font-size: 15px; }
.close-btn {
  background: none; border: none; font-size: 22px; cursor: pointer; color: #999;
}
.tabs {
  display: flex;
  gap: 4px;
  padding: 8px 12px;
  border-bottom: 1px solid #eee;
}
.tabs button {
  flex: 1;
  padding: 6px;
  border: 1px solid #ddd;
  background: #fafafa;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
}
.tabs button.active {
  background: var(--color-primary, #5b21b6);
  color: #fff;
  border-color: transparent;
}
.event-list, .trace-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}
.empty { color: #999; font-size: 13px; text-align: center; padding: 24px 8px; }
.event-row {
  display: flex;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  margin-bottom: 4px;
  background: #f8f8fc;
  font-size: 12px;
  align-items: flex-start;
}
.event-row.small { font-size: 11px; }
.event-type {
  flex-shrink: 0;
  font-weight: 600;
  color: var(--color-primary-strong, #5b21b6);
  min-width: 100px;
}
.event-payload { color: #555; word-break: break-all; }
.seq { color: #aaa; min-width: 28px; }
.run-block { margin-bottom: 10px; border: 1px solid #eee; border-radius: 8px; overflow: hidden; }
.run-header {
  display: flex;
  justify-content: space-between;
  padding: 8px 10px;
  background: #fafafa;
  cursor: pointer;
  font-size: 12px;
}
.run-meta { color: #888; }
.run-events { padding: 6px; background: #fff; }
.harness-panel-enter-active, .harness-panel-leave-active { transition: opacity 0.2s; }
.harness-panel-enter-from, .harness-panel-leave-to { opacity: 0; }
</style>
