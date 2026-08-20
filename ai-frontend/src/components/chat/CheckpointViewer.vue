<template>
  <Transition name="checkpoint-viewer">
    <div v-if="visible" class="checkpoint-modal" @click.self="onClose">
      <div class="modal-content">
        <div class="modal-header">
          <h3>🔧 工作流 Checkpoints</h3>
          <button class="close-btn" @click="onClose">×</button>
        </div>

        <div v-if="loading" class="loading">加载中…</div>
        <div v-else-if="error" class="error">{{ error }}</div>
        <div v-else-if="!hasCheckpoints" class="empty">
          <div class="empty-icon">📭</div>
          <p>该会话暂无 checkpoint 记录</p>
          <p class="hint">Agent 流程结束后会保存 checkpoint</p>
        </div>
        <div v-else>
          <div v-if="resuming" class="resume-banner">
            <span class="resume-spinner"></span>
            正在从断点继续执行…
          </div>
          <div v-else-if="resumeResult" class="resume-banner" :class="resumeResult.ok ? 'ok' : 'fail'">
            <strong>{{ resumeResult.title }}</strong>
            <span class="resume-detail">{{ resumeResult.detail }}</span>
          </div>
          <div
            v-for="wf in checkpoints"
            :key="wf.workflow_type"
            class="workflow-block"
          >
            <div class="workflow-header">
              <span class="workflow-type">{{ wf.workflow_type }}</span>
              <span v-if="wf.last_completed_step" class="last-step">
                当前: <strong>{{ wf.last_completed_step }}</strong>
              </span>
              <span v-else class="last-step muted">未完成任何步骤</span>
              <button
                v-if="wf.last_completed_step"
                class="resume-btn"
                :disabled="resuming"
                @click="resume"
              >
                ▶ 继续运行
              </button>
            </div>
            <div class="step-timeline">
              <div
                v-for="(step, idx) in wf.steps"
                :key="idx"
                :class="['step', { completed: step.step_name === wf.last_completed_step }]"
              >
                <div class="step-dot"></div>
                <div class="step-info">
                  <div class="step-name">{{ step.step_name }}</div>
                  <div class="step-time">{{ formatTime(step.created_at) }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { getCheckpoints, resumeWorkflow, type CheckpointStep } from '@/api/chat'

const props = defineProps<{
  visible: boolean
  sessionId: string | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const checkpoints = ref<CheckpointStep[]>([])
const loading = ref(false)
const error = ref('')
const resuming = ref(false)
const resumeResult = ref<{ ok: boolean; title: string; detail: string } | null>(null)

const hasCheckpoints = computed(() => checkpoints.value.length > 0)

async function load() {
  if (!props.sessionId || !props.visible) return
  loading.value = true
  error.value = ''
  try {
    const data = await getCheckpoints(props.sessionId)
    checkpoints.value = data.checkpoints || []
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    error.value = err.response?.data?.detail || err.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function resume() {
  if (!props.sessionId) return
  resuming.value = true
  resumeResult.value = null
  try {
    const res = await resumeWorkflow(props.sessionId)
    if (res.error) {
      resumeResult.value = {
        ok: false,
        title: '恢复失败',
        detail: `${res.error}${res.failed_at ? `（失败于 ${res.failed_at}）` : ''}`,
      }
    } else {
      const wfLabel = (res.workflow_type || '').replace(/_workflow$/, '')
      resumeResult.value = {
        ok: true,
        title: `已从断点继续完成（${wfLabel}）`,
        detail: res.answer ? res.answer.replace(/\s+/g, ' ').slice(0, 120) + '…' : '',
      }
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    resumeResult.value = { ok: false, title: '恢复失败', detail: err.response?.data?.detail || err.message || '未知错误' }
  } finally {
    resuming.value = false
    await load()
  }
}

onMounted(load)
watch(() => props.visible, (v) => { if (v) load() })
watch(() => props.sessionId, () => { if (props.visible) load() })

function onClose() {
  emit('close')
}

function formatTime(t: string) {
  if (!t) return ''
  try {
    const d = new Date(t)
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return t
  }
}
</script>

<style scoped>
.checkpoint-modal {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}
.modal-content {
  background: white;
  border-radius: 14px;
  width: 540px;
  max-width: 92vw;
  max-height: 80vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #eee;
}
.modal-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}
.close-btn {
  background: none;
  border: none;
  font-size: 24px;
  cursor: pointer;
  color: #999;
  padding: 0;
  line-height: 1;
}
.close-btn:hover { color: #333; }
.loading, .error, .empty {
  padding: 40px 20px;
  text-align: center;
  color: #888;
}
.error { color: var(--color-danger); }
.empty-icon {
  font-size: 40px;
  margin-bottom: 12px;
}
.empty .hint {
  font-size: 12px;
  color: #aaa;
  margin-top: 8px;
}
.resume-banner {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0 20px 16px;
  padding: 10px 14px;
  border-radius: 8px;
  background: #f0f7ff;
  border: 1px solid #cfe5ff;
  font-size: 13px;
  color: #1a5c9e;
}
.resume-banner.ok {
  background: #f0fdf4;
  border-color: #c6f0d0;
  color: #157347;
}
.resume-banner.fail {
  background: #fef2f2;
  border-color: #f7c9c9;
  color: #b02a37;
}
.resume-detail {
  font-size: 12px;
  color: inherit;
  opacity: 0.85;
}
.resume-spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid #cfe5ff;
  border-top-color: #1a5c9e;
  border-radius: 50%;
  animation: rspin 0.8s linear infinite;
}
@keyframes rspin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.workflows {
  padding: 16px 20px;
  overflow-y: auto;
}
.workflow-block {
  margin-bottom: 18px;
  padding: 12px;
  background: #fafafa;
  border-radius: 8px;
}
.workflow-block:last-child { margin-bottom: 0; }
.workflow-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.workflow-type {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-primary-strong);
  background: rgba(91, 33, 182, 0.1);
  padding: 3px 8px;
  border-radius: 4px;
}
.last-step {
  font-size: 12px;
  color: #555;
}
.last-step.muted { color: #aaa; }
.resume-btn {
  margin-left: auto;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  background: var(--color-primary, #5b21b6);
  border: none;
  border-radius: 6px;
  padding: 5px 10px;
  cursor: pointer;
  transition: opacity 0.2s;
}
.resume-btn:hover:not(:disabled) { opacity: 0.85; }
.resume-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.step-timeline {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.step {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  position: relative;
}
.step-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ddd;
  flex-shrink: 0;
}
.step.completed .step-dot {
  background: linear-gradient(135deg, #667eea, #764ba2);
}
.step-info {
  flex: 1;
  display: flex;
  justify-content: space-between;
  font-size: 12px;
}
.step-name { color: #333; font-weight: 500; }
.step.completed .step-name { color: var(--color-primary-strong); font-weight: 600; }
.step-time { color: #999; }
.checkpoint-viewer-enter-active,
.checkpoint-viewer-leave-active {
  transition: opacity 0.2s;
}
.checkpoint-viewer-enter-from,
.checkpoint-viewer-leave-to {
  opacity: 0;
}
</style>