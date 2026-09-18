import { describe, expect, it } from 'vitest'
import { useToolProgress } from '@/composables/useToolProgress'
import { useChatStream } from '@/composables/useChatStream'

describe('useToolProgress', () => {
  it('tracks start/end with duration', () => {
    const { activeTools, handleToolEvent, resetTools } = useToolProgress()
    resetTools()
    handleToolEvent({
      type: 'tool',
      name: 'search_video_chunks',
      status: 'start',
      label: '检索视频片段',
    })
    handleToolEvent({
      type: 'tool',
      name: 'search_video_chunks',
      status: 'end',
      label: '检索视频片段',
      ok: true,
      duration_ms: 42,
    })
    expect(activeTools.value).toHaveLength(1)
    expect(activeTools.value[0].status).toBe('done')
    expect(activeTools.value[0].durationMs).toBe(42)
  })

  it('marks failed tool end', () => {
    const { activeTools, handleToolEvent, resetTools } = useToolProgress()
    resetTools()
    handleToolEvent({ type: 'tool', name: 'retrieve_knowledge', status: 'start', label: '检索' })
    handleToolEvent({ type: 'tool', name: 'retrieve_knowledge', status: 'end', label: '检索', ok: false })
    expect(activeTools.value[0].status).toBe('failed')
  })
})

describe('useChatStream', () => {
  it('routes status/tool/meta and returns actionable events', () => {
    const { applyStreamEvent, workflowStage, activeTools, resetStreamUi } = useChatStream()
    resetStreamUi()
    expect(applyStreamEvent({ type: 'status', stage: 'routing', label: '分析意图' })).toBeNull()
    expect(workflowStage.value).toBe('routing')
    expect(applyStreamEvent({
      type: 'tool',
      name: 'search_video_chunks',
      status: 'start',
      label: '检索视频片段',
    })).toBeNull()
    expect(activeTools.value).toHaveLength(1)
    const text = applyStreamEvent({ type: 'text', content: 'hello' })
    expect(text).toEqual({ type: 'text', content: 'hello' })
  })
})
