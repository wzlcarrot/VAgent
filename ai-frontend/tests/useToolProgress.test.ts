import { describe, expect, it } from 'vitest'
import { useToolProgress } from '@/composables/useToolProgress'
import type { StreamToolEvent } from '@/api/chat'

function ev(patch: Partial<StreamToolEvent>): StreamToolEvent {
  return { type: 'tool', name: 'tool', status: 'start', label: '工具', ...patch }
}

describe('useToolProgress', () => {
  it('handles start / end(ok) / end(failed) / reset', () => {
    const { activeTools, handleToolEvent, resetTools } = useToolProgress()

    handleToolEvent(ev({ name: 'search', label: '检索' }))
    expect(activeTools.value).toHaveLength(1)
    expect(activeTools.value[0]).toMatchObject({ name: 'search', label: '检索', status: 'running' })

    handleToolEvent(ev({ name: 'search', status: 'end', ok: true, duration_ms: 12 }))
    expect(activeTools.value[0].status).toBe('done')
    expect(activeTools.value[0].durationMs).toBe(12)

    handleToolEvent(ev({ name: 'other', label: '别的' }))
    handleToolEvent(ev({ name: 'other', status: 'end', ok: false }))
    expect(activeTools.value[1].status).toBe('failed')

    resetTools()
    expect(activeTools.value).toHaveLength(0)
  })

  it('label falls back to name; unknown status ignored', () => {
    const { activeTools, handleToolEvent } = useToolProgress()
    handleToolEvent(ev({ name: 'toolA', label: '' }))
    expect(activeTools.value[0].label).toBe('toolA')

    handleToolEvent(ev({ name: 'toolA', status: 'weird' }))
    expect(activeTools.value).toHaveLength(1)
  })

  it('end event without matching running tool is a no-op', () => {
    const { activeTools, handleToolEvent } = useToolProgress()
    handleToolEvent(ev({ name: 'ghost', status: 'end', ok: true }))
    expect(activeTools.value).toHaveLength(0)
  })
})
