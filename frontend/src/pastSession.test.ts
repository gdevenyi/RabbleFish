import { describe, expect, it } from 'vitest'
import type { SessionsApi } from './api'
import type { PastSession, ServerEvent, SourceInfo } from './contract'
import { pastSessionApi, pastSessionEvents } from './pastSession'
import { initialState, reduceAll, sortedSegments } from './timeline/state'

const past: PastSession = {
  id: '2026-10-30T10-00-00',
  started_at: 1000,
  ended_at: 1010,
  length: 10,
  state: 'interrupted',
  interrupted: true,
  target_lang: 'en',
  speakers: [{ id: 'mon#1', label: 'Speaker 1', display_name: null }],
  segments: 1,
  audio_files: 1,
  events: [
    { type: 'session', state: 'interrupted', started_at: 1000, target_lang: 'en', ended_at: 1010 },
    { type: 'speaker', id: 'mon#1', source_key: 'mon', label: 'Speaker 1', display_name: null },
    { type: 'segment', id: 'mon/1', source_key: 'mon', speaker_id: 'mon#1', start: 1, end: 3, text: 'bonjour à tous', words: [], lang: 'fr' },
    { type: 'translation', segment_id: 'mon/1', text: 'hello everyone', target_lang: 'en' },
    { type: 'audio_file', source_key: 'mon', path: 'audio/mon-001.pcm', start: 0.2, sample_rate: 16000, format: 's16le' },
  ],
}
const sources: SourceInfo[] = [{ key: 'mon', kind: 'monitor', description: 'Speakers', selected: true, mode: 'diarize' }]

describe('past session', () => {
  it('builds the Timeline state from the replayed snapshot, over any earlier state', () => {
    const before = reduceAll(initialState(), [
      { event: { type: 'speaker', id: 'old#1', source_key: 'old', label: 'Old', display_name: null }, at: 1 },
    ])
    const s = reduceAll(before, pastSessionEvents(past, sources, 2000))
    expect(s.session).toEqual({ state: 'interrupted', startedAt: 1000, targetLang: 'en' })
    expect(Object.keys(s.speakers)).toEqual(['mon#1'])
    expect(sortedSegments(s).map((x) => x.text)).toEqual(['bonjour à tous'])
    expect(s.translations['mon/1'].text).toBe('hello everyone')
    // The Source descriptions come from the current Sources, which are not selected.
    expect(s.sources).toEqual([{ ...sources[0], selected: false }])
  })

  it('clears the live state at an interrupted session event, like at a stop', () => {
    const live: ServerEvent[] = [
      { type: 'session', state: 'started', started_at: 1000 },
      { type: 'partial', source_key: 'mon', text: 'bon', audio_time: 1 },
      { type: 'translation_status', state: 'ready', target_lang: 'en' },
      { type: 'session', state: 'interrupted', started_at: 1000 },
    ]
    const s = reduceAll(
      initialState(),
      live.map((event) => ({ event, at: 1 })),
    )
    expect(s.partials).toEqual({})
    expect(s.translationStatus).toBeNull()
  })

  it('sends rename and merge to the past Session and applies the returned events', async () => {
    const calls: string[] = []
    const applied: ServerEvent[] = []
    const sessions: SessionsApi = {
      list: async () => [],
      open: async () => past,
      renameSpeaker: async (id, speakerId, name) => {
        calls.push(`rename ${id} ${speakerId} ${name}`)
        return { type: 'speaker', id: speakerId, source_key: 'mon', label: 'Speaker 1', display_name: name }
      },
      mergeSpeakers: async (id, from, into) => {
        calls.push(`merge ${id} ${from} ${into}`)
        return { type: 'merge', from_speaker_id: from, into_speaker_id: into }
      },
      remove: async () => {},
    }
    const api = pastSessionApi(sessions, past.id, (e) => applied.push(e))
    await api.renameSpeaker('mon#1', 'Alice')
    await api.mergeSpeakers('mon#2', 'mon#1')
    expect(calls).toEqual([`rename ${past.id} mon#1 Alice`, `merge ${past.id} mon#2 mon#1`])
    expect(applied.map((e) => e.type)).toEqual(['speaker', 'merge'])
    await expect(api.startSession('en')).rejects.toThrow(/read-only/)
    await expect(api.updateSource('mon', { selected: true })).rejects.toThrow(/read-only/)
  })
})
