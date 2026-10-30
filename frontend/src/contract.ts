// Events from the backend on /ws, as the endpoint contract defines them
// (gdevenyi/live-transcribe-translate#11). All times are seconds since the Session started.

export type SourceMode = 'single' | 'diarize'

export interface SourceInfo {
  key: string
  kind: 'microphone' | 'monitor'
  description: string
  selected: boolean
  mode: SourceMode
}

export interface Word {
  w: string
  start: number
  end: number
}

export interface SessionEvent {
  type: 'session'
  state: 'started' | 'stopped'
  /** Unix time in seconds (the same clock as `heartbeat.server_time`). */
  started_at: number | null
}

export interface SourceStatusEvent {
  type: 'source_status'
  source_key: string
  state: 'connecting' | 'live' | 'error'
  message?: string | null
}

export interface SpeakerEvent {
  type: 'speaker'
  id: string
  source_key: string
  label: string
  display_name: string | null
}

export interface PartialEvent {
  type: 'partial'
  source_key: string
  text: string
  audio_time: number
}

export interface SegmentEvent {
  type: 'segment'
  id: string
  source_key: string
  speaker_id: string
  start: number
  end: number
  text: string
  words: Word[]
  lang: string | null
}

export interface TranslationEvent {
  type: 'translation'
  segment_id: string
  text: string
  target_lang: string
}

export interface MergeEvent {
  type: 'merge'
  from_speaker_id: string
  into_speaker_id: string
}

export interface HelloEvent {
  type: 'hello'
  version: string
}

export interface HeartbeatEvent {
  type: 'heartbeat'
  seq: number
  server_time: number
}

export interface SourcesEvent {
  type: 'sources'
  sources: SourceInfo[]
}

export type ServerEvent =
  | HelloEvent
  | HeartbeatEvent
  | SourcesEvent
  | SessionEvent
  | SourceStatusEvent
  | SpeakerEvent
  | PartialEvent
  | SegmentEvent
  | TranslationEvent
  | MergeEvent
