import { type ExportFormat, exportUrl } from './api'

const FORMATS: { format: ExportFormat; name: string; title: string }[] = [
  { format: 'md', name: 'Markdown', title: 'Download the transcript as Markdown (.md)' },
  { format: 'json', name: 'JSON', title: 'Download the transcript, the words and the audio files as JSON (.json)' },
]

/**
 * Export of the open Session: a past Session by its ID, or (with `null`) the live or last
 * Session. Each link downloads the file that the backend makes from the Session's log.
 */
export function ExportMenu({ sessionId, disabled }: { sessionId: string | null; disabled?: boolean }) {
  return (
    <span className="export" data-testid="export">
      Export
      {FORMATS.map(({ format, name, title }) =>
        disabled ? (
          <span key={format} className="export-link disabled" aria-disabled="true" title="No session to export">
            {name}
          </span>
        ) : (
          <a key={format} className="export-link" href={exportUrl(sessionId, format)} download title={title} data-testid={`export-${format}`}>
            {name}
          </a>
        ),
      )}
    </span>
  )
}
