import { describe, expect, it } from 'vitest'
import type { ServerEvent } from '../contract'
import { type AppState, endpointChip, initialState, mergeTargets, reduceAll, sortedSegments, warningHint, warningLabel } from './state'

const run = (events: ServerEvent[], state: AppState = initialState(), at = 1000) =>
  reduceAll(
    state,
    events.map((event) => ({ event, at })),
  )

const speaker = (id: string, source_key = 'mon', label = id): ServerEvent => ({
  type: 'speaker',
  id,
  source_key,
  label,
  display_name: null,
})
const segment = (id: string, speaker_id: string, start: number, end: number, lang: string | null = 'en'): ServerEvent => ({
  type: 'segment',
  id,
  source_key: speaker_id.split('#')[0],
  speaker_id,
  start,
  end,
  text: id,
  words: [],
  lang,
})

describe('reducer', () => {
  it('keeps Segments sorted by start time when they arrive out of order', () => {
    const s = run([speaker('mon#1'), segment('b', 'mon#1', 5, 6), segment('a', 'mon#1', 1, 2), segment('c', 'mon#1', 3, 4)])
    expect(sortedSegments(s).map((x) => x.id)).toEqual(['a', 'c', 'b'])
  })

  it('gives the same state when the snapshot repeats events', () => {
    const events = [speaker('mon#1'), segment('a', 'mon#1', 1, 2), { type: 'merge', from_speaker_id: 'mon#2', into_speaker_id: 'mon#1' } as ServerEvent]
    const once = run(events)
    const twice = run(events, once)
    expect(twice.segmentOrder).toEqual(['a'])
    expect(twice.merges).toHaveLength(1)
    expect(Object.keys(twice.speakers)).toEqual(['mon#1'])
  })

  it('replaces a Partial text and clears it with a Segment of the same Source only', () => {
    let s = run([
      { type: 'partial', source_key: 'mon', text: 'hel', audio_time: 3 },
      { type: 'partial', source_key: 'mic', text: 'bon', audio_time: 3 },
      { type: 'partial', source_key: 'mon', text: 'hello th', audio_time: 4 },
    ])
    expect(s.partials.mon.text).toBe('hello th')
    expect(s.partials.mon.since).toBe(1.5) // kept from the first Partial text
    s = run([speaker('mon#1'), segment('a', 'mon#1', 1.6, 4)], s)
    expect(s.partials.mon).toBeUndefined()
    expect(s.partials.mic.text).toBe('bon')
  })

  it('starts a Partial text after the last Segment of its Source', () => {
    const s = run([speaker('mon#1'), segment('a', 'mon#1', 1, 9.5), { type: 'partial', source_key: 'mon', text: 'x', audio_time: 10 }])
    expect(s.partials.mon.since).toBe(9.5)
  })

  it('keeps a Segment whose Speaker is not known yet', () => {
    const s = run([segment('a', 'mon#7', 1, 2)])
    expect(s.speakers['mon#7'].label).toBe('mon#7')
    const s2 = run([{ type: 'speaker', id: 'mon#7', source_key: 'mon', label: 'Speaker 7', display_name: null }], s)
    expect(s2.speakers['mon#7'].label).toBe('Speaker 7')
    expect(s2.speakers['mon#7'].order).toBe(s.speakers['mon#7'].order)
  })

  it('applies a rename from a speaker event', () => {
    const s = run([speaker('mon#1', 'mon', 'Speaker 1'), { type: 'speaker', id: 'mon#1', source_key: 'mon', label: 'Speaker 1', display_name: 'Alice' }])
    expect(s.speakers['mon#1']).toMatchObject({ label: 'Speaker 1', displayName: 'Alice' })
  })

  it('resets the transcript on hello and on a new Session', () => {
    const s = run([{ type: 'session', state: 'started', started_at: 100 }, speaker('mon#1'), segment('a', 'mon#1', 1, 2)])
    expect(run([{ type: 'hello', version: '1' }], s).segmentOrder).toEqual([])
    const same = run([{ type: 'session', state: 'started', started_at: 100 }], s)
    expect(same.segmentOrder).toEqual(['a'])
    const next = run([{ type: 'session', state: 'started', started_at: 200 }], s)
    expect(next.segmentOrder).toEqual([])
    expect(next.session).toEqual({ state: 'started', startedAt: 200, targetLang: null })
  })

  it('keeps the transcript and clears the Partial texts when the Session stops', () => {
    const s = run([
      { type: 'session', state: 'started', started_at: 100 },
      speaker('mon#1'),
      segment('a', 'mon#1', 1, 2),
      { type: 'partial', source_key: 'mon', text: 'x', audio_time: 3 },
      { type: 'session', state: 'stopped', started_at: 100 },
    ])
    expect(s.segmentOrder).toEqual(['a'])
    expect(s.partials).toEqual({})
  })

  it('records the clock offset from a heartbeat', () => {
    const s = reduceAll(initialState(), [{ event: { type: 'heartbeat', seq: 1, server_time: 1010 }, at: 1000 }])
    expect(s.clockOffset).toBe(10)
  })

  it('ignores a Merge that closes a loop', () => {
    const s = run([
      { type: 'merge', from_speaker_id: 'a', into_speaker_id: 'b' },
      { type: 'merge', from_speaker_id: 'b', into_speaker_id: 'a' },
    ])
    expect(s.merges).toHaveLength(1)
  })

  it('keeps the Target language, the translations and the translation status of the Session', () => {
    let s = run([
      { type: 'session', state: 'started', started_at: 1, target_lang: 'en' },
      speaker('mon#1'),
      segment('a', 'mon#1', 1, 2, 'fr'),
      { type: 'translation', segment_id: 'a', text: 'hello', target_lang: 'en' },
      { type: 'translation_status', state: 'error', target_lang: 'en', message: 'no translation model' },
    ])
    expect(s.session.targetLang).toBe('en')
    expect(s.translations.a).toEqual({ text: 'hello', targetLang: 'en' })
    expect(s.translationStatus).toEqual({ state: 'error', targetLang: 'en', message: 'no translation model' })
    s = run([{ type: 'session', state: 'stopped', started_at: 1, target_lang: 'en' }], s)
    expect(s.translationStatus).toBeNull()
    expect(s.translations.a.text).toBe('hello') // the transcript stays after the Session
  })
})

describe('Source warning', () => {
  const status = (state: 'connecting' | 'live' | 'error', warning?: 'muted' | 'silent' | null): ServerEvent => ({
    type: 'source_status',
    source_key: 'mon',
    state,
    message: null,
    ...(warning === undefined ? {} : { warning }),
  })

  it('is set by source_status and cleared when the warning goes away', () => {
    let s = run([status('connecting', 'muted')])
    expect(s.sourceStatus.mon).toEqual({ state: 'connecting', message: null, warning: 'muted' })
    s = run([status('live', 'muted')], s)
    expect(s.sourceStatus.mon.warning).toBe('muted')
    s = run([status('live', null)], s)
    expect(s.sourceStatus.mon).toEqual({ state: 'live', message: null, warning: null })
    s = run([status('live', 'silent')], s)
    expect(s.sourceStatus.mon.warning).toBe('silent')
  })

  it('is null for an event of an older backend without the field', () => {
    expect(run([status('live')]).sourceStatus.mon.warning).toBeNull()
  })

  it('has a short label and a hint', () => {
    expect(warningLabel('muted')).toBe('Muted')
    expect(warningLabel('silent')).toBe('No sound')
    expect(warningHint('muted')).toMatch(/muted/)
    expect(warningHint('silent')).toMatch(/silence/)
  })
})

describe('mergeTargets', () => {
  it('follows a chain of Merges', () => {
    const t = mergeTargets([
      { from: 'a', into: 'b', receivedAt: 0 },
      { from: 'b', into: 'c', receivedAt: 0 },
    ])
    expect(t.get('a')).toBe('c')
    expect(t.get('b')).toBe('c')
    expect(t.has('c')).toBe(false)
  })
})

describe('settings and the endpoint state', () => {
  const status = (state: 'checking' | 'ready' | 'not_ready' | 'unreachable', missing: string[] = [], message: string | null = null) =>
    ({
      type: 'endpoint_status',
      state,
      asr_url: 'http://127.0.0.1:8080',
      translation_url: 'http://127.0.0.1:8080',
      capabilities: ['transcription', 'diarization', 'translation'].filter((c) => !missing.includes(c)),
      missing,
      message,
      checked_at: state === 'checking' ? null : 1000,
    }) as const

  it('keeps the default Target language of hello, also after a hello with none', () => {
    let s = run([{ type: 'hello', version: '1', default_target_language: 'fr' }])
    expect(s.defaultTargetLang).toBe('fr')
    s = run([{ type: 'hello', version: '1' }], s)
    expect(s.defaultTargetLang).toBe('fr')
  })

  it('keeps the last endpoint state, also after a hello', () => {
    let s = run([status('checking'), status('unreachable', [], 'http://127.0.0.1:8080/ready: refused')])
    expect(s.endpointStatus?.state).toBe('unreachable')
    s = run([{ type: 'hello', version: '1' }], s)
    expect(s.endpointStatus?.state).toBe('unreachable')
  })

  it('labels the endpoint chip', () => {
    expect(endpointChip(status('ready'))).toMatchObject({ label: 'ready', tone: 'live' })
    expect(endpointChip(status('ready', ['translation'], 'no translation model'))).toMatchObject({ label: 'ready, no translation', tone: 'connecting' })
    expect(endpointChip(status('checking'))).toMatchObject({ label: 'checking', tone: 'connecting' })
    expect(endpointChip(status('not_ready'))).toMatchObject({ label: 'not ready', tone: 'error' })
    const down = endpointChip(status('unreachable', [], 'http://127.0.0.1:8080/ready: refused'))
    expect(down).toMatchObject({ label: 'unreachable', tone: 'error' })
    expect(down.hint).toContain('refused')
  })
})
