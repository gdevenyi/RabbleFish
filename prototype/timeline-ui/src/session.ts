// PROTOTYPE: throwaway. A fake session with a scripted live tail.
// History: 0..20 min is already finalized at load. Live tail: the clock starts
// at 20:00 and runs. Notable events in the tail (use "Next event" to jump):
//   20:27  Speaker 4 switches from English to French
//   20:34  correction: one segment moves from Speaker 2 to Speaker 5
//   20:54  Speaker 9 joins (more than 8 speakers)
//   21:10  correction: Speaker 6 was a false split, all its segments merge into Speaker 3
//   21:37  two speakers overlap for 6 s, one segment has a code-switch inside it
import { useEffect, useMemo, useRef, useState } from 'react'
import type { Actions, Lang, Move, Run, ScriptEvent, Segment, SessionView, Source, Speaker } from './types'

export const SOURCES: Source[] = [
  { id: 'mic', name: 'Headset mic', mode: 'single' },
  { id: 'call', name: 'Call audio (monitor)', mode: 'diarize' },
]

export const SPEAKERS: Speaker[] = [
  { id: 'mic-0', label: 'Mic', sourceId: 'mic' },
  ...Array.from({ length: 9 }, (_, i) => ({ id: `call-${i + 1}`, label: `Speaker ${i + 1}`, sourceId: 'call' })),
]

const EN = [
  'Okay, can everyone hear me now?',
  'I think the main risk is the latency on the laptop.',
  'We measured about three seconds end to end last week.',
  'Let me share my screen for a moment.',
  'That number looks too high for the French model.',
  'Can we move the review to Thursday afternoon?',
  'The diarization keeps the labels stable after about ten seconds.',
  'I agree, but we need a fallback for the ninth speaker.',
  'Sorry, I was on mute.',
  'Let us write that down as an action item.',
  'The export should keep the speaker names.',
  'I have a question about the translation step.',
  'Yes, exactly.',
  'Could you repeat the last part, please?',
]

const FR: [string, string][] = [
  ['Je pense que le modèle est assez rapide.', 'I think the model is fast enough.'],
  ['On peut tester ça demain matin.', 'We can test that tomorrow morning.'],
  ['Attends, je ne suis pas sûr de comprendre.', 'Wait, I am not sure I understand.'],
  ['La traduction arrive avec un petit délai.', 'The translation arrives with a small delay.'],
  ['Oui, tout à fait.', 'Yes, absolutely.'],
  ['Il faut garder les noms des participants.', 'We must keep the names of the participants.'],
  ['Le son de la salle est mauvais aujourd’hui.', 'The sound in the room is bad today.'],
  ['On revient à ce point après la pause.', 'We come back to this point after the break.'],
]

// Deterministic pseudo-random numbers, so every reload shows the same session.
function rng(seed: number) {
  let s = seed >>> 0
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 2 ** 32
  }
}

function seg(id: string, speakerId: string, start: number, dur: number, lang: Lang, runs: Run[], translation?: string): Segment {
  return { id, speakerId, originalSpeakerId: speakerId, start, end: start + dur, lang, runs, translation }
}

function makeSentence(r: () => number, lang: Lang): { runs: Run[]; translation?: string } {
  if (lang === 'en') return { runs: [{ lang: 'en', text: EN[Math.floor(r() * EN.length)] }] }
  const [fr, en] = FR[Math.floor(r() * FR.length)]
  return { runs: [{ lang: 'fr', text: fr }], translation: en }
}

function buildScript(): { segments: Segment[]; events: ScriptEvent[]; notable: { t: number; note: string }[] } {
  const r = rng(42)
  const segments: Segment[] = []
  let n = 0
  const id = () => `s${++n}`
  // Speaker language habits in the history.
  const frRate: Record<string, number> = { 'mic-0': 0.1, 'call-1': 0.0, 'call-2': 0.5, 'call-3': 0.2, 'call-4': 0.0, 'call-5': 0.9, 'call-6': 0.3, 'call-7': 0.6, 'call-8': 0.1 }
  // Speakers active in the history; Speaker 8 joins at 10 min.
  let t = 2
  while (t < 1200) {
    const active = ['mic-0', 'call-1', 'call-2', 'call-3', 'call-4', 'call-5', 'call-6', 'call-7', ...(t > 600 ? ['call-8'] : [])]
    const sp = active[Math.floor(r() * active.length)]
    const lang: Lang = r() < frRate[sp] ? 'fr' : 'en'
    const dur = 2 + r() * 9
    const { runs, translation } = makeSentence(r, lang)
    segments.push(seg(id(), sp, t, dur, lang, runs, translation))
    const gap = r()
    // Mostly short gaps, sometimes overlap, sometimes a long silence.
    t += gap < 0.12 ? dur * 0.5 : gap < 0.94 ? dur + 0.5 + r() * 4 : dur + 40 + r() * 90
  }

  // Live tail, hand-written so the events are easy to watch.
  const L = 1200
  const tail: Segment[] = [
    seg(id(), 'call-1', L + 2, 5, 'en', [{ lang: 'en', text: 'Okay, we are back. Where were we?' }]),
    seg(id(), 'mic-0', L + 8, 4, 'en', [{ lang: 'en', text: 'We were on the latency numbers.' }]),
    seg(id(), 'call-4', L + 13, 4, 'en', [{ lang: 'en', text: 'Right, I had a comment on that.' }]),
    seg(id(), 'call-4', L + 18, 6, 'fr', [{ lang: 'fr', text: 'En fait, je vais continuer en français, c’est plus simple.' }], 'Actually, I will continue in French, it is simpler.'),
    seg(id(), 'call-2', L + 25, 3, 'en', [{ lang: 'en', text: 'Fine with me.' }]), // finalized at L+31, moved to Speaker 5 at L+34
    seg(id(), 'call-3', L + 31, 5, 'en', [{ lang: 'en', text: 'The new numbers are on the shared drive.' }]),
    seg(id(), 'call-4', L + 37, 7, 'fr', [{ lang: 'fr', text: 'Les chiffres de mardi sont meilleurs que prévu.' }], 'The numbers from Tuesday are better than expected.'),
    seg(id(), 'call-9', L + 46, 5, 'en', [{ lang: 'en', text: 'Hi all, sorry I am late, I just joined.' }]),
    seg(id(), 'mic-0', L + 52, 3, 'en', [{ lang: 'en', text: 'Welcome!' }]),
    seg(id(), 'call-6', L + 56, 6, 'en', [{ lang: 'en', text: 'I can send the summary after the call.' }]),
    seg(id(), 'call-7', L + 63, 5, 'fr', [{ lang: 'fr', text: 'Parfait, merci.' }], 'Perfect, thank you.'),
    seg(id(), 'call-1', L + 75, 8, 'en', [{ lang: 'en', text: 'Next topic is the column layout for many speakers.' }]),
    seg(id(), 'call-2', L + 79, 6, 'en', [{ lang: 'en', text: 'Sorry, go ahead, I interrupted you.' }]), // overlaps call-1
    seg(id(), 'call-5', L + 86, 8, 'fr', [{ lang: 'fr', text: 'Moi je pense que' }, { lang: 'en', text: 'the horizontal scroll is fine' }, { lang: 'fr', text: 'si les noms restent visibles.' }], 'I think the horizontal scroll is fine if the names stay visible.'),
  ]
  const movedSeg = tail[4]
  segments.push(...tail)

  // Generic chatter after the scripted part so the tail never runs dry.
  t = L + 100
  while (t < 3600) {
    const active = ['mic-0', 'call-1', 'call-2', 'call-3', 'call-4', 'call-5', 'call-7', 'call-8', 'call-9']
    const sp = active[Math.floor(r() * active.length)]
    const lang: Lang = r() < (frRate[sp] ?? 0.3) ? 'fr' : 'en'
    const dur = 2 + r() * 8
    const { runs, translation } = makeSentence(r, lang)
    segments.push(seg(id(), sp, t, dur, lang, runs, translation))
    t += dur + 0.5 + r() * 6
  }

  const call6 = segments.filter((s) => s.speakerId === 'call-6').map((s) => s.id)
  const events: ScriptEvent[] = [
    { t: L + 34, kind: 'reassign', segmentIds: [movedSeg.id], toSpeakerId: 'call-5', note: 'Correction: one segment moved from Speaker 2 to Speaker 5' },
    { t: L + 70, kind: 'reassign', segmentIds: call6, toSpeakerId: 'call-3', note: 'Correction: Speaker 6 was a false split; all its segments merged into Speaker 3' },
  ]
  // t is when the event is visible on screen (segments show FINALIZE_DELAY s after they end).
  const notable = [
    { t: L + 27, note: 'Speaker 4 switches from English to French' },
    { t: L + 34.5, note: events[0].note },
    { t: L + 54, note: 'Speaker 9 joins (more than 8 speakers)' },
    { t: L + 70.5, note: events[1].note },
    { t: L + 97, note: 'Overlap (Speakers 1 and 2) and a code-switch inside one segment (Speaker 5)' },
  ]
  return { segments, events, notable }
}

const SCRIPT = buildScript()
export const START_CLOCK = 1200
// A segment shows when it is finalized: FINALIZE_DELAY seconds after it ends (2-5 s target).
const FINALIZE_DELAY = 3

export function useSession(): { view: SessionView; actions: Actions } {
  const [clock, setClock] = useState(START_CLOCK)
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(1)
  const [follow, setFollow] = useState(true)
  const [showTranslation, setShowTranslation] = useState(true)
  const [displayNames, setDisplayNames] = useState<Record<string, string>>({ 'mic-0': 'Me' })
  const [renameNote, setRenameNote] = useState('')
  const speedRef = useRef(speed)
  speedRef.current = speed

  useEffect(() => {
    if (!playing) return
    const h = setInterval(() => setClock((c) => c + 0.1 * speedRef.current), 100)
    return () => clearInterval(h)
  }, [playing])

  const view = useMemo<SessionView>(() => {
    const owner = new Map<string, string>()
    const recentMoves: Move[] = []
    let lastEvent = 'Session started at 00:00; history loaded up to 20:00'
    for (const ev of SCRIPT.events) {
      if (ev.t > clock) continue
      for (const sid of ev.segmentIds) {
        const s = SCRIPT.segments.find((x) => x.id === sid)!
        if (s.end + FINALIZE_DELAY > ev.t) continue // not visible yet when the correction happened
        if (clock - ev.t < 6) recentMoves.push({ segmentId: sid, fromSpeakerId: owner.get(sid) ?? s.originalSpeakerId, toSpeakerId: ev.toSpeakerId, at: ev.t })
        owner.set(sid, ev.toSpeakerId)
      }
    }
    for (const n of SCRIPT.notable) if (n.t <= clock) lastEvent = `${fmt(n.t)} ${n.note}`
    if (renameNote) lastEvent = renameNote
    const segments = SCRIPT.segments
      .filter((s) => s.end + FINALIZE_DELAY <= clock)
      .map((s) => (owner.has(s.id) ? { ...s, speakerId: owner.get(s.id)! } : s))
    const used = new Set(segments.map((s) => s.speakerId))
    return {
      clock,
      playing,
      speed,
      targetLang: 'en',
      showTranslation,
      follow,
      sources: SOURCES,
      speakers: SPEAKERS.filter((s) => used.has(s.id)),
      segments,
      displayNames,
      recentMoves,
      lastEvent,
    }
  }, [clock, playing, speed, showTranslation, follow, displayNames, renameNote])

  const actions: Actions = {
    rename: (speakerId, name) => {
      setDisplayNames((d) => {
        const next = { ...d }
        if (name.trim()) next[speakerId] = name.trim()
        else delete next[speakerId]
        return next
      })
      const label = SPEAKERS.find((s) => s.id === speakerId)?.label
      setRenameNote(`Renamed ${label} to "${name.trim() || label}"`)
    },
    setFollow,
    togglePlay: () => setPlaying((p) => !p),
    setSpeed,
    jumpToNextEvent: () => {
      setRenameNote('')
      // Jump and pause, so the event stays on screen until the user presses Play.
      setPlaying(false)
      setClock((c) => SCRIPT.notable.find((n) => n.t > c + 0.25)?.t ?? c)
    },
    toggleTranslation: () => setShowTranslation((v) => !v),
  }
  return { view, actions }
}

// --- helpers that variants can use -------------------------------------------

export function fmt(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = String(s % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${String(m).padStart(2, '0')}:${ss}`
}

export function nameOf(view: SessionView, speakerId: string): string {
  return view.displayNames[speakerId] ?? SPEAKERS.find((s) => s.id === speakerId)?.label ?? speakerId
}

// True when this segment's language differs from the previous visible segment of the same speaker.
export function isLanguageSwitch(view: SessionView, segment: Segment): boolean {
  let prev: Segment | undefined
  for (const s of view.segments) {
    if (s.id === segment.id) break
    if (s.speakerId === segment.speakerId) prev = s
  }
  return !!prev && prev.lang !== segment.lang
}

export function hasCodeSwitch(segment: Segment): boolean {
  return new Set(segment.runs.map((r) => r.lang)).size > 1
}

export function moveOf(view: SessionView, segmentId: string): Move | undefined {
  return view.recentMoves.find((m) => m.segmentId === segmentId)
}
