import { describe, expect, it } from 'vitest'
import type { ServerEvent } from '../contract'
import { languageSwitches } from './language'
import { buildModel, formatDuration, formatTime, liveEdge } from './model'
import { findOverlaps } from './overlap'
import { initialState, reduceAll, type Segment } from './state'

const seg = (id: string, speakerId: string, start: number, end: number, lang: string | null = 'en'): Segment => ({
  id,
  sourceKey: 'mon',
  speakerId,
  start,
  end,
  text: id,
  words: [],
  lang,
})
const self = (s: Segment) => s.speakerId

describe('languageSwitches', () => {
  it('marks a change of language for the same Speaker', () => {
    const segs = [seg('1', 'a', 0, 1, 'en'), seg('2', 'b', 1, 2, 'fr'), seg('3', 'a', 2, 3, 'fr'), seg('4', 'a', 3, 4, 'fr')]
    expect([...languageSwitches(segs, self)]).toEqual(['3'])
  })

  it('does not start or end a switch on a Segment with no language', () => {
    const segs = [seg('1', 'a', 0, 1, 'en'), seg('2', 'a', 1, 2, null), seg('3', 'a', 2, 3, 'en'), seg('4', 'a', 3, 4, null), seg('5', 'a', 4, 5, 'fr')]
    expect([...languageSwitches(segs, self)]).toEqual(['5'])
  })

  it('computes the switches again after a Merge', () => {
    const segs = [seg('1', 'a', 0, 1, 'en'), seg('2', 'b', 1, 2, 'fr'), seg('3', 'a', 2, 3, 'en')]
    expect(languageSwitches(segs, self).size).toBe(0)
    const merged = (s: Segment) => (s.speakerId === 'b' ? 'a' : s.speakerId)
    expect([...languageSwitches(segs, merged)]).toEqual(['2', '3'])
  })
})

describe('findOverlaps', () => {
  it('finds overlaps between different Speakers only', () => {
    const segs = [seg('1', 'a', 0, 5), seg('2', 'a', 4, 6), seg('3', 'b', 5.5, 8), seg('4', 'c', 7, 9)]
    const o = findOverlaps(segs, self)
    expect(o.bands).toEqual([
      { start: 5.5, end: 6 },
      { start: 7, end: 8 },
    ])
    expect([...o.ids].sort()).toEqual(['2', '3', '4'])
  })

  it('finds no overlap after the two Speakers merge', () => {
    const segs = [seg('1', 'a', 0, 5), seg('2', 'b', 4, 6)]
    expect(findOverlaps(segs, self).bands).toHaveLength(1)
    expect(findOverlaps(segs, () => 'a').bands).toHaveLength(0)
  })

  it('joins bands that touch', () => {
    const segs = [seg('1', 'a', 0, 10), seg('2', 'b', 2, 4), seg('3', 'c', 3, 6)]
    expect(findOverlaps(segs, self).bands).toEqual([{ start: 2, end: 6 }])
  })
})

describe('buildModel', () => {
  const events: ServerEvent[] = [
    { type: 'sources', sources: [{ key: 'mic', kind: 'microphone', description: 'Mic', selected: true, mode: 'single' }] },
    { type: 'speaker', id: 'mon#1', source_key: 'mon', label: 'Speaker 1', display_name: null },
    { type: 'speaker', id: 'mon#2', source_key: 'mon', label: 'Speaker 2', display_name: null },
    { type: 'speaker', id: 'mic#0', source_key: 'mic', label: 'Mic', display_name: null },
    { type: 'segment', id: 's1', source_key: 'mon', speaker_id: 'mon#1', start: 0, end: 2, text: 'x', words: [], lang: 'en' },
    { type: 'segment', id: 's2', source_key: 'mon', speaker_id: 'mon#2', start: 3, end: 4, text: 'y', words: [], lang: 'fr' },
    { type: 'segment', id: 's3', source_key: 'mon', speaker_id: 'mon#1', start: 5, end: 6, text: 'z', words: [], lang: 'en' },
  ]

  it('groups the Columns by Source in the order of the Sources list', () => {
    const m = buildModel(reduceAll(initialState(), events.map((event) => ({ event, at: 0 }))))
    expect(m.groups.map((g) => [g.description, g.speakers.map((s) => s.id)])).toEqual([
      ['Mic', ['mic#0']],
      ['mon', ['mon#1', 'mon#2']],
    ])
  })

  it('removes the Column of a merged Speaker and moves its Segments', () => {
    const all = [...events, { type: 'merge', from_speaker_id: 'mon#2', into_speaker_id: 'mon#1' } as ServerEvent]
    const m = buildModel(reduceAll(initialState(), all.map((event) => ({ event, at: 0 }))))
    expect(m.groups[1].speakers.map((s) => s.id)).toEqual(['mon#1'])
    expect(m.bySpeaker.get('mon#1')!.map((s) => s.id)).toEqual(['s1', 's2', 's3'])
    expect([...m.switches]).toEqual(['s2', 's3'])
    expect(m.lastSpokeAt.get('mon#1')).toBe(6)
  })
})

describe('liveEdge', () => {
  it('uses the server clock while the Session runs', () => {
    const s = reduceAll(initialState(), [
      { event: { type: 'heartbeat', seq: 1, server_time: 1005 }, at: 1000 },
      { event: { type: 'session', state: 'started', started_at: 900 }, at: 1000 },
    ])
    expect(liveEdge(s, 1010)).toBe(115)
  })

  it('is never before the newest data', () => {
    const s = reduceAll(initialState(), [
      { event: { type: 'session', state: 'started', started_at: 1000 }, at: 1000 },
      { event: { type: 'partial', source_key: 'mon', text: 'x', audio_time: 30 }, at: 1000 },
    ])
    expect(liveEdge(s, 1010)).toBe(30)
  })
})

describe('format', () => {
  it('formats times and durations', () => {
    expect(formatTime(65.9)).toBe('01:05')
    expect(formatTime(3725)).toBe('1:02:05')
    expect(formatDuration(45)).toBe('45 s')
    expect(formatDuration(125)).toBe('2 min 05 s')
  })
})
