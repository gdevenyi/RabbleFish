import { describe, expect, it } from 'vitest'
import { segmentBoxHeight } from './segmentBox'

describe('segmentBoxHeight', () => {
  it('grows from the height of the speech up to the next Segment', () => {
    expect(segmentBoxHeight(40, 100)).toEqual({ min: 40, max: 100, thin: false })
  })

  it('gives a short Segment the minimum height when there is room', () => {
    expect(segmentBoxHeight(5, 100)).toEqual({ min: 22, max: 100, thin: false })
  })

  it('stops before the next Segment when the minimum height does not fit', () => {
    expect(segmentBoxHeight(5, 16)).toEqual({ min: 16, max: 16, thin: false })
  })

  it('stops before the next Segment when the speech overlaps it after a Merge', () => {
    expect(segmentBoxHeight(200, 30)).toEqual({ min: 30, max: 30, thin: false })
  })

  it('shows a bar when the room is too small for text', () => {
    expect(segmentBoxHeight(5, 8)).toEqual({ min: 8, max: 8, thin: true })
  })

  it('has no height when the next Segment starts at the same place', () => {
    expect(segmentBoxHeight(5, -2)).toEqual({ min: 0, max: 0, thin: true })
  })

  it('has no maximum when nothing is below the box', () => {
    expect(segmentBoxHeight(5, Infinity)).toEqual({ min: 22, max: undefined, thin: false })
    expect(segmentBoxHeight(300, Infinity)).toEqual({ min: 300, max: undefined, thin: false })
  })
})
