import { ref } from 'vue'
import type { StreamToolEvent } from '@/api/chat'

export interface ToolBlock {
  name: string
  label: string
  status: 'running' | 'done' | 'failed'
  durationMs?: number
}

export function useToolProgress() {
  const activeTools = ref<ToolBlock[]>([])

  function resetTools() {
    activeTools.value = []
  }

  function handleToolEvent(event: StreamToolEvent) {
    if (event.status === 'start') {
      activeTools.value.push({
        name: event.name,
        label: event.label || event.name,
        status: 'running',
      })
      return
    }
    if (event.status === 'end') {
      for (let i = activeTools.value.length - 1; i >= 0; i -= 1) {
        const block = activeTools.value[i]
        if (block.name === event.name && block.status === 'running') {
          block.status = event.ok === false ? 'failed' : 'done'
          if (typeof event.duration_ms === 'number') {
            block.durationMs = event.duration_ms
          }
          return
        }
      }
    }
  }

  return {
    activeTools,
    resetTools,
    handleToolEvent,
  }
}
