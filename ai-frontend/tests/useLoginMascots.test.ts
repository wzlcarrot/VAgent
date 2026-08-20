import { describe, expect, it } from 'vitest'
import { calcFaceOffset, calcPupilOffset, rectCenter } from '@/composables/useLoginMascots'

describe('useLoginMascots', () => {
  it('clamps face offset', () => {
    const far = calcFaceOffset(0, 0, 10000, 10000)
    expect(far.faceX).toBe(15)
    expect(far.faceY).toBe(10)
    expect(far.bodySkew).toBe(-6)
  })

  it('is identity at the center', () => {
    const mid = calcFaceOffset(100, 100, 100, 100)
    expect(mid).toEqual({ faceX: 0, faceY: 0, bodySkew: 0 })
  })

  it('caps pupil distance', () => {
    const p = calcPupilOffset(0, 0, 1000, 0, 5)
    expect(p.x).toBeCloseTo(5, 5)
    expect(p.y).toBeCloseTo(0, 5)
  })

  it('rectCenter uses yFactor', () => {
    const { cx, cy } = rectCenter({ left: 10, width: 20, top: 0, height: 30 }, 1 / 3)
    expect(cx).toBe(20)
    expect(cy).toBe(10)
  })
})
