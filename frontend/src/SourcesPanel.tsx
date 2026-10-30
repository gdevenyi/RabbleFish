import type { Api } from './api'
import type { SourceInfo, SourceMode } from './contract'

const GROUPS: { kind: SourceInfo['kind']; title: string }[] = [
  { kind: 'microphone', title: 'Microphones' },
  { kind: 'monitor', title: 'Output monitors' },
]

/** Source selection and mode. They cannot change while a Session runs. */
export function SourcesPanel({ sources, api, disabled, onError }: { sources: SourceInfo[]; api: Api; disabled: boolean; onError: (e: unknown) => void }) {
  return (
    <section aria-label="Sources" className="sources">
      {disabled && <p className="sources-note">You cannot change the Sources while a Session runs.</p>}
      <div className="sources-groups">
        {GROUPS.map(({ kind, title }) => {
          const group = sources.filter((s) => s.kind === kind)
          return (
            <fieldset key={kind} disabled={disabled}>
              <legend>{title}</legend>
              {group.length === 0 && <p>None found.</p>}
              <ul>
                {group.map((s) => (
                  <li key={s.key} data-testid="source">
                    <label>
                      <input type="checkbox" checked={s.selected} onChange={(e) => api.updateSource(s.key, { selected: e.target.checked }).catch(onError)} />{' '}
                      {s.description}
                    </label>
                    <select
                      aria-label={`Mode of ${s.description}`}
                      value={s.mode}
                      onChange={(e) => api.updateSource(s.key, { mode: e.target.value as SourceMode }).catch(onError)}
                    >
                      <option value="single">Single speaker</option>
                      <option value="diarize">Diarize</option>
                    </select>
                  </li>
                ))}
              </ul>
            </fieldset>
          )
        })}
      </div>
    </section>
  )
}
