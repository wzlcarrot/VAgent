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
        <div v-else class="workflows">
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
import { getCheckpoints, type CheckpointStep } from '@/api/chat'

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
  color: #5b21b6;
  background: rgba(91, 33, 182, 0.1);
  padding: 3px 8px;
  border-radius: 4px;
}
.last-step {
  font-size: 12px;
  color: #555;
}
.last-step.muted { color: #aaa; }
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
.step.completed .step-name { color: #5b21b6; font-weight: 600; }
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