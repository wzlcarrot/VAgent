import { ref } from 'vue'
import type { HarnessEvent, StreamApprovalEvent, StreamEvent } from '@/api/chat'
import { useToolProgress } from '@/composables/useToolProgress'

export interface ChatStreamUiState {
  workflowStage: string
  workflowLabel: string
  workflowRoute: { winner_type: string; confidence: number; method: string } | null
  harnessLiveEvents: HarnessEvent[]
}

export function useChatStream() {
  const workflowStage = ref('')
  const workflowLabel = ref('')
  const workflowRoute = ref<ChatStreamUiState['workflowRoute']>(null)
  const harnessLiveEvents = ref<HarnessEvent[]>([])
  const pendingApproval = ref<StreamApprovalEvent | null>(null)

  const { activeTools, resetTools, handleToolEvent } = useToolProgress()

  function resetStreamUi() {
    workflowStage.value = ''
    workflowLabel.value = ''
    workflowRoute.value = null
    harnessLiveEvents.value = []
    pendingApproval.value = null
    resetTools()
  }

  function clearPendingApproval() {
    pendingApproval.value = null
  }

  function applyStreamEvent(event: StreamEvent) {
    if (event.type === 'status') {
      workflowStage.value = event.stage
      workflowLabel.value = event.label
      return null
    }
    if (event.type === 'meta') {
      workflowRoute.value = event.meta
      return null
    }
    if (event.type === 'tool') {
      handleToolEvent(event)
      if (event.status === 'start') {
        workflowStage.value = 'retrieval'
        workflowLabel.value = event.label || '工具执行中'
      }
      return null
    }
    if (event.type === 'retry') {
      workflowStage.value = 'retry'
      const reason = event.error_type || (event.status_code ? `HTTP ${event.status_code}` : '网络')
      workflowLabel.value = `${event.op} 重试 ${event.next_attempt}/${event.max_attempts}（${reason}，${event.wait_s}s）`
      return null
    }
    if (event.type === 'approval') {
      pendingApproval.value = event
      workflowStage.value = 'approval'
      workflowLabel.value = `等待确认：${event.label || event.tool}`
      return null
    }
    if (event.type === 'harness') {
      harnessLiveEvents.value.push(event)
      return null
    }
    return event
  }

  return {
    workflowStage,
    workflowLabel,
    workflowRoute,
    harnessLiveEvents,
    pendingApproval,
    activeTools,
    resetStreamUi,
    clearPendingApproval,
    applyStreamEvent,
  }
}
