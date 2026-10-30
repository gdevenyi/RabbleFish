import { describe, expect, it } from 'vitest'
import { exportUrl } from './api'

describe('exportUrl', () => {
  it('exports a past Session by its ID', () => {
    expect(exportUrl('2026-10-30T10-00-00', 'md')).toBe('/api/sessions/2026-10-30T10-00-00/export?format=md')
    expect(exportUrl('2026-10-30T10-00-00', 'json')).toBe('/api/sessions/2026-10-30T10-00-00/export?format=json')
  })

  it('exports the live or last Session with no ID', () => {
    expect(exportUrl(null, 'json')).toBe('/api/session/export?format=json')
  })
})
