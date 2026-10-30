import { type SourceInfo, type SourceMode, updateSource } from './useBackendSocket'

const GROUPS: { kind: SourceInfo['kind']; title: string }[] = [
  { kind: 'microphone', title: 'Microphones' },
  { kind: 'monitor', title: 'Output monitors' },
]

export function SourcesPanel({ sources }: { sources: SourceInfo[] }) {
  return (
    <section aria-label="Sources">
      <h2>Sources</h2>
      {GROUPS.map(({ kind, title }) => {
        const group = sources.filter((s) => s.kind === kind)
        return (
          <div key={kind}>
            <h3>{title}</h3>
            {group.length === 0 && <p>None found.</p>}
            <ul style={{ listStyle: 'none', padding: 0 }}>
              {group.map((s) => (
                <li key={s.key} data-testid="source" style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '2px 0' }}>
                  <label style={{ flex: 1 }}>
                    <input
                      type="checkbox"
                      checked={s.selected}
                      onChange={(e) => void updateSource(s.key, { selected: e.target.checked })}
                    />{' '}
                    {s.description}
                  </label>
                  <select
                    aria-label={`Mode of ${s.description}`}
                    value={s.mode}
                    onChange={(e) => void updateSource(s.key, { mode: e.target.value as SourceMode })}
                  >
                    <option value="single">Single speaker</option>
                    <option value="diarize">Diarize</option>
                  </select>
                </li>
              ))}
            </ul>
          </div>
        )
      })}
    </section>
  )
}
