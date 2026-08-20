<template>
  <div class="workflow-indicator" v-if="visible">
    <div class="indicator-header">
      <svg class="spinner" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10" stroke-dasharray="60" stroke-dashoffset="20"></circle>
      </svg>
      <span>智能处理中...</span>
    </div>
    <div class="steps">
      <div
        v-for="(step, index) in steps"
        :key="index"
        class="step"
        :class="step.status"
      >
        <div class="step-dot">
          <svg v-if="step.status === 'completed'" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
        </div>
        <div class="step-line" v-if="index < steps.length - 1"></div>
        <span class="step-label">{{ step.label }}</span>
      </div>
    </div>
    <div class="current-step" v-if="currentStepLabel">
      当前: {{ currentStepLabel }}
    </div>
    <div class="route-decision" v-if="routeText">
      <span class="route-badge">路由</span>
      <span class="route-text">{{ routeText }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue'

const props = defineProps<{
  visible: boolean
  stage: string
  label: string
  route?: { winner_type: string; confidence: number; method: string } | null
}>()

interface Step {
  label: string
  status: 'pending' | 'active' | 'completed'
}

const WINNER_LABELS: Record<string, string> = {
  video_qa_workflow: '视频问答',
  recommend_workflow: '视频推荐',
  user_data_workflow: '个人数据',
  chat_workflow: '平台对话',
}

const METHOD_LABELS: Record<string, string> = {
  keyword_only: '关键词命中',
  keyword_low_conf: '关键词低置信',
  consensus: '关键词+语义一致',
  consensus_low_conf: '低置信共识',
  llm: 'LLM 裁决',
  fallback: '语义兜底',
  fallback_low_conf: '低置信兜底',
  fallback_priority: '优先级降级',
}

const routeText = computed(() => {
  if (!props.route) return ''
  const wf = WINNER_LABELS[props.route.winner_type] || props.route.winner_type
  const method = METHOD_LABELS[props.route.method] || props.route.method
  const conf = (props.route.confidence * 100).toFixed(0)
  return `${wf} · ${method} · 置信度 ${conf}%`
})

const stepConfig = [
  { key: 'routing', label: '分析意图' },
  { key: 'retrieval', label: '检索知识' },
  { key: 'generating', label: '生成回复' },
]

const steps = ref<Step[]>([])
const currentStepLabel = ref('')

watch(() => props.visible, (newVal) => {
  if (newVal) {
    initSteps()
  } else {
    currentStepLabel.value = ''
  }
}, { immediate: true })

watch(() => props.stage, (newStage) => {
  if (!newStage) return
  if (newStage === 'done') {
    steps.value.forEach(s => { s.status = 'completed' })
    currentStepLabel.value = '完成'
    return
  }
  let hit = false
  for (const config of stepConfig) {
    const step = steps.value.find(s => s.label === config.label)
    if (!step) continue
    if (config.key === newStage) {
      step.status = 'active'
      currentStepLabel.value = props.label || config.label
      hit = true
    } else if (!hit) {
      step.status = 'completed'
    }
  }
})

function initSteps() {
  steps.value = stepConfig.map(c => ({
    label: c.label,
    status: 'pending' as const,
  }))
  currentStepLabel.value = ''
}
</script>

<style scoped>
.workflow-indicator {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  padding: var(--space-md);
  margin-bottom: var(--space-md);
  animation: slideIn 0.3s ease-out;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.indicator-header {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  font-size: 14px;
  font-weight: 500;
  color: var(--color-primary);
  margin-bottom: var(--space-md);
}

.spinner {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.steps {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin-bottom: var(--space-sm);
}

.step {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
}

.step-dot {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 2px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition-fast);
}

.step.pending .step-dot {
  border-color: var(--color-border);
}

.step.active .step-dot {
  border-color: var(--color-primary);
  background: var(--color-primary);
  animation: step-pulse 1.2s ease-in-out infinite;
  box-shadow: 0 0 0 4px var(--color-ring);
}

@keyframes step-pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.15); }
}

.step.active .step-dot::after {
  content: '';
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: white;
  animation: pulse 1s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.step.completed .step-dot {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: white;
}

.step-line {
  width: 40px;
  height: 2px;
  background: var(--color-border);
  margin: 0 var(--space-xs);
}

.step.completed + .step .step-line,
.step.completed .step-line {
  background: var(--color-primary);
}

.step-label {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.step.active .step-label {
  color: var(--color-primary);
  font-weight: 500;
}

.step.completed .step-label {
  color: var(--color-text);
}

.current-step {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-top: var(--space-sm);
}

.route-decision {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  margin-top: var(--space-sm);
  padding-top: var(--space-sm);
  border-top: 1px dashed var(--color-border);
  font-size: 12px;
}

.route-badge {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  color: var(--color-primary);
  border: 1px solid var(--color-primary);
  border-radius: 4px;
  padding: 0 6px;
  line-height: 18px;
}

.route-text {
  color: var(--color-text-secondary);
  word-break: break-all;
}
</style>
