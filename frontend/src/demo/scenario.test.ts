import { describe, expect, it } from 'vitest'
import { buildModel } from '../timeline/model'
import { initialState, reduceAll } from '../timeline/state'
import { buildScenario, MONITOR } from './scenario'

describe('demo scenario', () => {
  const events = buildScenario(400)
  const state = reduceAll(
    initialState(),
    events.map((e) => ({ event: e.event, at: e.t })),
  )
  const model = buildModel(state)

  it('is sorted by time', () => {
    for (let i = 1; i < events.length; i++) expect(events[i].t).toBeGreaterThanOrEqual(events[i - 1].t)
  })

  it('sends each speaker event before the first Segment of that Speaker', () => {
    const seen = new Set<string>()
    for (const { event } of events) {
      if (event.type === 'speaker') seen.add(event.id)
      if (event.type === 'segment') expect(seen.has(event.speaker_id)).toBe(true)
    }
  })

  it('covers the features of the Timeline', () => {
    expect(model.groups.map((g) => g.key)).toContain(MONITOR)
    expect(Object.keys(state.speakers).length).toBeGreaterThanOrEqual(10) // new ids after the reconnect
    expect(Object.keys(state.translations).length).toBeGreaterThan(0)
    expect(model.switches.size).toBeGreaterThan(0)
    expect(model.overlaps.bands.length).toBeGreaterThan(0)
    expect(model.segments.some((s) => s.lang === null)).toBe(true)
  })
})
