import { describe, expect, it } from 'vitest'
import { buildTimeScale } from './timeScale'

const opts = { pxPerSec: 10, foldAfter: 20, margin: 3, foldPx: 26 }

describe('buildTimeScale', () => {
  it('is linear when no silence is longer than the limit', () => {
    const ts = buildTimeScale([{ start: 0, end: 10 }, { start: 25, end: 30 }], 32, opts)
    expect(ts.folds).toEqual([])
    expect(ts.y(12.5)).toBe(125)
    expect(ts.height).toBe(320)
  })

  it('folds a long silence and keeps the margins linear', () => {
    const ts = buildTimeScale([{ start: 0, end: 10 }, { start: 70, end: 80 }], 80, opts)
    expect(ts.folds).toHaveLength(1)
    const f = ts.folds[0]
    expect(f).toMatchObject({ start: 13, end: 67, silence: 60, y: 130 })
    expect(ts.y(10)).toBe(100)
    expect(ts.y(13)).toBe(130)
    expect(ts.y(67)).toBeCloseTo(156)
    // After the fold, the axis is linear again with the same scale.
    expect(ts.y(70) - ts.y(67)).toBeCloseTo(30)
    expect(ts.height).toBeCloseTo(130 + 26 + 13 * 10)
  })

  it('maps y back to time (inverse), also inside a fold', () => {
    const ts = buildTimeScale([{ start: 0, end: 10 }, { start: 70, end: 80 }, { start: 200, end: 210 }], 215, opts)
    for (const t of [0, 5, 13, 20, 40, 66.9, 67, 75, 100, 199, 205, 215]) expect(ts.time(ts.y(t))).toBeCloseTo(t)
  })

  it('is monotonic', () => {
    const ts = buildTimeScale([{ start: 30, end: 31 }, { start: 100, end: 120 }], 400, opts)
    let prev = -1
    for (let t = 0; t <= 400; t += 0.5) {
      const y = ts.y(t)
      expect(y).toBeGreaterThanOrEqual(prev)
      prev = y
    }
  })

  it('joins overlapping speech of different Speakers before it finds silences', () => {
    const ts = buildTimeScale([{ start: 0, end: 10 }, { start: 5, end: 40 }, { start: 45, end: 50 }], 50, opts)
    expect(ts.folds).toEqual([])
  })

  it('folds the silence before the Live edge, so the Live edge stays in place while the silence grows', () => {
    const a = buildTimeScale([{ start: 0, end: 10 }], 60, opts)
    const b = buildTimeScale([{ start: 0, end: 10 }], 600, opts)
    expect(a.folds).toHaveLength(1)
    expect(a.height).toBeCloseTo(b.height)
    expect(b.folds[0].silence).toBe(590)
  })

  it('folds a long silence at the start of the Session', () => {
    const ts = buildTimeScale([{ start: 50, end: 55 }], 55, opts)
    expect(ts.folds[0]).toMatchObject({ start: 3, end: 47, y: 30 })
  })
})
