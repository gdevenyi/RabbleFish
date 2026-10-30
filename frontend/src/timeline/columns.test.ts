import { describe, expect, it } from 'vitest'
import { layoutColumns, togglePin } from './columns'

const base = { now: 1000, width: 2000, pins: {}, activeWindow: 120, wideMin: 200, collapsedWidth: 34 }
const wide = (r: { id: string; wide: boolean }[]) => r.filter((c) => c.wide).map((c) => c.id)

describe('layoutColumns', () => {
  it('makes recent Speakers wide and collapses idle Speakers', () => {
    const r = layoutColumns(
      [
        { id: 'a', lastSpokeAt: 990 },
        { id: 'b', lastSpokeAt: 500 },
        { id: 'c', lastSpokeAt: 881 },
      ],
      base,
    )
    expect(wide(r)).toEqual(['a', 'c'])
    expect(r.find((c) => c.id === 'b')).toMatchObject({ wide: false, active: false, pinned: false })
  })

  it('keeps a pinned Speaker wide and a collapsed Speaker narrow', () => {
    const r = layoutColumns(
      [
        { id: 'a', lastSpokeAt: 990 },
        { id: 'b', lastSpokeAt: 10 },
      ],
      { ...base, pins: { a: 'collapsed', b: 'wide' } },
    )
    expect(wide(r)).toEqual(['b'])
    expect(r[1].pinned).toBe(true)
  })

  it('collapses the least recent Speakers when the Columns do not fit the width', () => {
    const cols = ['a', 'b', 'c', 'd', 'e'].map((id, i) => ({ id, lastSpokeAt: 950 + i }))
    // 5 * 34 = 170; (600 - 170) / 166 = 2 wide Columns.
    const r = layoutColumns(cols, { ...base, width: 600 })
    expect(wide(r)).toEqual(['d', 'e'])
    const used = r.reduce((w, c) => w + (c.wide ? 200 : 34), 0)
    expect(used).toBeLessThanOrEqual(600)
  })

  it('keeps pinned Columns before recent ones when it must collapse some', () => {
    const cols = ['a', 'b', 'c'].map((id, i) => ({ id, lastSpokeAt: 950 + i }))
    const r = layoutColumns(cols, { ...base, width: 34 * 3 + 166, pins: { a: 'wide' } })
    expect(wide(r)).toEqual(['a'])
  })

  it('makes the most recent Speaker wide when all are idle', () => {
    const r = layoutColumns(
      [
        { id: 'a', lastSpokeAt: 100 },
        { id: 'b', lastSpokeAt: 300 },
        { id: 'c', lastSpokeAt: null },
      ],
      base,
    )
    expect(wide(r)).toEqual(['b'])
  })

  it('makes a Column wide when it is forced (Partial text)', () => {
    const r = layoutColumns(
      [
        { id: 'a', lastSpokeAt: 990 },
        { id: 'b', lastSpokeAt: 10, forceWide: true },
      ],
      { ...base, width: 34 * 2 + 166 },
    )
    expect(wide(r)).toEqual(['b'])
  })
})

describe('togglePin', () => {
  it('cycles collapsed -> pinned wide -> automatic', () => {
    const p1 = togglePin({}, { id: 'a', wide: false, pinned: false, active: false })
    expect(p1).toEqual({ a: 'wide' })
    const p2 = togglePin(p1, { id: 'a', wide: true, pinned: true, active: false })
    expect(p2).toEqual({})
    const p3 = togglePin({}, { id: 'a', wide: true, pinned: false, active: true })
    expect(p3).toEqual({ a: 'collapsed' })
  })
})
