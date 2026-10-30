// DEV ONLY. A scripted Session made of contract events, for the `?demo` mode.
// The monitor Source replays a real NeMo-Speech.cpp recording (nemoFixture.json: English
// meeting talk, then French reading, 5 diarized Speakers in 88 s). The microphone Source
// has a short script with overlaps, a Language switch and short Segments with no language.
import type { ServerEvent, SourceInfo } from '../contract'
import fixture from './nemoFixture.json'

export interface TimedEvent {
  /** Session time (seconds) when the backend sends the event. */
  t: number
  event: ServerEvent
}

export const MIC = 'alsa_input.usb-Blue_Yeti-00.analog-stereo'
export const MONITOR = 'alsa_output.pci-0000_00_1f.3.analog-stereo.monitor'

export const DEMO_SOURCES: SourceInfo[] = [
  { key: MIC, kind: 'microphone', description: 'Yeti USB microphone', selected: true, mode: 'single' },
  { key: 'alsa_input.pci-0000_00_1f.3.analog-stereo', kind: 'microphone', description: 'Built-in microphone', selected: false, mode: 'single' },
  { key: MONITOR, kind: 'monitor', description: 'Laptop speakers (monitor)', selected: true, mode: 'diarize' },
]

const TARGET = 'en'

interface MicLine {
  at: number
  text: string
  lang: string | null
  translation?: string
}

// Lines of the microphone user, relative to the start of each block.
const MIC_LINES: MicLine[] = [
  { at: 18.0, text: 'Sorry, can you share the file again?', lang: 'en' },
  { at: 28.6, text: 'Okay.', lang: null },
  { at: 47.0, text: 'Yes, I can do Monday afternoon.', lang: 'en' },
  { at: 58.0, text: 'Attendez, je pense que la lecture commence maintenant.', lang: 'fr', translation: 'Wait, I think the reading starts now.' },
  { at: 74.0, text: "C'est le passage du deuxième chapitre.", lang: 'fr', translation: 'It is the passage from the second chapter.' },
]
// Lines in the long silence between blocks.
const MIC_ALONE: MicLine[] = [
  { at: 0, text: 'I am back. The call dropped for a moment, so let me reconnect the audio.', lang: 'en' },
  { at: 6.5, text: 'Can everyone hear me now?', lang: 'en' },
]

interface Block {
  offset: number
  /** NeMo speaker number to Speaker id suffix. */
  ids: (n: number) => number
  mic: MicLine[]
}

function segId(n: number) {
  return `seg-${String(n).padStart(5, '0')}`
}

/** Builds the scripted Session, sorted by time, up to about `until` seconds. */
export function buildScenario(until = 3600): TimedEvent[] {
  const out: TimedEvent[] = []
  const known = new Set<string>()
  let n = 0
  const emit = (t: number, event: ServerEvent) => out.push({ t, event })
  const speaker = (t: number, id: string, source_key: string, label: string) => {
    if (known.has(id)) return
    known.add(id)
    emit(t, { type: 'speaker', id, source_key, label, display_name: null })
  }

  const micSpeaker = `${MIC}#0`
  const micLine = (start: number, line: MicLine) => {
    const words = line.text.split(' ')
    const step = 0.32
    const end = start + words.length * step
    // Partial text grows word by word, then the final arrives after endpointing.
    for (let i = 1; i <= words.length; i++)
      emit(start + 0.6 + i * step, { type: 'partial', source_key: MIC, text: words.slice(0, i).join(' '), audio_time: start + i * step })
    const ft = end + 1.4
    speaker(ft, micSpeaker, MIC, 'Yeti USB microphone')
    const id = segId(n++)
    emit(ft, {
      type: 'segment',
      id,
      source_key: MIC,
      speaker_id: micSpeaker,
      start,
      end,
      text: line.text,
      words: words.map((w, i) => ({ w, start: start + i * step, end: start + (i + 1) * step })),
      lang: line.lang,
    })
    if (line.translation) emit(ft + 1.2, { type: 'translation', segment_id: id, text: line.translation, target_lang: TARGET })
  }

  const block = ({ offset, ids, mic }: Block) => {
    for (const p of fixture.partials) emit(offset + p.t, { type: 'partial', source_key: MONITOR, text: p.text, audio_time: offset + p.audio_time })
    for (const f of fixture.finals) {
      for (const s of f.segments) {
        const num = ids(s.speaker)
        const sid = `${MONITOR}#${num}`
        speaker(offset + f.t, sid, MONITOR, `Speaker ${num}`)
        const id = segId(n++)
        emit(offset + f.t, {
          type: 'segment',
          id,
          source_key: MONITOR,
          speaker_id: sid,
          start: offset + s.start,
          end: offset + s.end,
          text: s.text,
          words: s.words.map((w) => ({ w: w.w, start: offset + w.start, end: offset + w.end })),
          lang: s.lang,
        })
        if ('translation' in s && s.translation) emit(offset + f.t + 1.5, { type: 'translation', segment_id: id, text: s.translation, target_lang: TARGET })
      }
    }
    for (const line of mic) micLine(offset + line.at, line)
  }

  emit(0, { type: 'source_status', source_key: MIC, state: 'connecting', message: null })
  emit(0, { type: 'source_status', source_key: MONITOR, state: 'connecting', message: null })
  emit(0.4, { type: 'source_status', source_key: MIC, state: 'live', message: null })
  emit(0.5, { type: 'source_status', source_key: MONITOR, state: 'live', message: null })

  // Block 1: the recording with Speakers 1-5.
  block({ offset: 4, ids: (s) => s, mic: MIC_LINES })
  // A long silence (it folds), then the microphone alone, then a reconnect of the monitor.
  const alone = 4 + fixture.duration + 55
  for (const line of MIC_ALONE) micLine(alone + line.at, line)
  const drop = alone + 3
  emit(drop, { type: 'source_status', source_key: MONITOR, state: 'connecting', message: 'Connection to the ASR endpoint lost. Reconnecting.' })
  emit(drop + 4, { type: 'source_status', source_key: MONITOR, state: 'live', message: null })
  // Block 2 onwards: after the reconnect the Speakers have new ids (6-10), as the contract says.
  let offset = alone + 14
  while (offset < until) {
    block({ offset, ids: (s) => s + 5, mic: MIC_LINES })
    offset += fixture.duration + 24 // the 24 s silence between repeats folds too
  }
  return out.sort((a, b) => a.t - b.t)
}
