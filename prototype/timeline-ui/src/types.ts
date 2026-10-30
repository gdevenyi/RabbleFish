// PROTOTYPE: throwaway. Shared data model for all timeline variants.
// Terms follow GLOSSARY.md: Session, Source, Speaker, Display name, Segment,
// Language switch, Translation, Target language, Timeline, Column.

export type Lang = 'en' | 'fr'

export interface Source {
  id: string
  name: string
  mode: 'single' | 'diarize'
}

export interface Speaker {
  id: string
  label: string // generated label, e.g. "Speaker 3"
  sourceId: string
}

// One part of a segment in one language. A segment with more than one run
// has a language switch inside it (code-switch).
export interface Run {
  lang: Lang
  text: string
}

export interface Segment {
  id: string
  speakerId: string // after any diarization corrections that have happened
  originalSpeakerId: string // as first finalized
  start: number // seconds since session start
  end: number
  lang: Lang // dominant language
  runs: Run[]
  translation?: string // into the target language; absent when lang === target
}

export type ScriptEvent =
  | { t: number; kind: 'reassign'; segmentIds: string[]; toSpeakerId: string; note: string }

export interface Move {
  segmentId: string
  fromSpeakerId: string
  toSpeakerId: string
  at: number // session clock when the correction happened
}

// What every variant receives. Everything is already derived for the current clock.
export interface SessionView {
  clock: number // seconds since session start
  playing: boolean
  speed: number
  targetLang: Lang
  showTranslation: boolean
  follow: boolean // auto-follow the live edge
  sources: Source[]
  speakers: Speaker[] // only speakers that have at least one visible segment, in column order
  segments: Segment[] // finalized and visible, sorted by start
  displayNames: Record<string, string> // speakerId -> display name
  recentMoves: Move[] // corrections in the last 6 s of session time
  lastEvent: string
}

export interface Actions {
  rename: (speakerId: string, name: string) => void
  setFollow: (follow: boolean) => void
  togglePlay: () => void
  setSpeed: (speed: number) => void
  jumpToNextEvent: () => void
  toggleTranslation: () => void
}
