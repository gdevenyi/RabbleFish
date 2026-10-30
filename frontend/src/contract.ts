// Events from the backend on /ws, as the endpoint contract defines them
// (gdevenyi/live-transcribe-translate#11). All times are seconds since the Session started.

export type SourceMode = 'single' | 'diarize'

export interface SourceInfo {
  key: string
  kind: 'microphone' | 'monitor'
  description: string
  selected: boolean
  mode: SourceMode
  /** PipeWire reports the node as muted (older backends do not send it). */
  muted?: boolean
}

export interface Word {
  w: string
  start: number
  end: number
}

export interface SessionEvent {
  type: 'session'
  /** "interrupted" is only in a saved Session: the app ended without a stop. */
  state: 'started' | 'stopped' | 'interrupted'
  /** Unix time in seconds (the same clock as `heartbeat.server_time`). */
  started_at: number | null
  /** The Target language of the Session. */
  target_lang?: string | null
  /** Unix time in seconds of the end ("stopped" and "interrupted" only). */
  ended_at?: number | null
}

export interface SourceStatusEvent {
  type: 'source_status'
  source_key: string
  state: 'connecting' | 'live' | 'error'
  message?: string | null
  /** "muted": the Source is quiet and PipeWire reports it as muted.
   * "silent": the Source gave only silence for a set time (default 30 s).
   * A change of the warning alone sends the event again with the same state. */
  warning?: SourceWarning | null
}

export type SourceWarning = 'muted' | 'silent'


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

/** The state of the translation endpoint in this Session. */
export interface TranslationStatusEvent {
  type: 'translation_status'
  state: 'ready' | 'error'
  target_lang: string
  message?: string | null
}

export interface MergeEvent {
  type: 'merge'
  from_speaker_id: string
  into_speaker_id: string
}

/** One saved audio file of a Source: raw PCM16, mono. */
export interface AudioFileEvent {
  type: 'audio_file'
  source_key: string
  /** Relative to the Session directory. */
  path: string
  /** Session time of the first sample. */
  start: number
  sample_rate: number
  format: string
}

export interface HelloEvent {
  type: 'hello'
  version: string
  /** The `default_target_language` setting: the first value of "Translate to". */
  default_target_language?: string
}

/**
 * The state of the model endpoint (not a Session event, never saved). The backend checks
 * it at its start, at each Session start, and again every 30 s while it is not ready.
 */
export interface EndpointStatusEvent {
  type: 'endpoint_status'
  state: 'checking' | 'ready' | 'not_ready' | 'unreachable'
  /** The http:// form of the ASR endpoint. */
  asr_url: string
  translation_url: string
  /** Of "transcription", "diarization", "translation". */
  capabilities: string[]
  missing: string[]
  message: string | null
  /** Unix seconds; null while the first check runs. */
  checked_at: number | null
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
  | EndpointStatusEvent
  | HeartbeatEvent
  | SourcesEvent
  | SessionEvent
  | SourceStatusEvent
  | SpeakerEvent
  | PartialEvent
  | SegmentEvent
  | TranslationEvent
  | TranslationStatusEvent
  | MergeEvent
  | AudioFileEvent

/** One past Session in `GET /api/sessions`. */
export interface PastSessionSummary {
  id: string
  started_at: number | null
  ended_at: number | null
  /** Seconds. */
  length: number
  state: 'started' | 'stopped' | 'interrupted'
  interrupted: boolean
  target_lang: string | null
  speakers: { id: string; label: string; display_name: string | null }[]
  segments: number
  audio_files: number
}

/** `GET /api/sessions/{id}`: the summary and the replayed snapshot of the Session. */
export interface PastSession extends PastSessionSummary {
  events: ServerEvent[]
}
