import { describe, expect, it } from 'vitest'
import { scoreBandIndex } from '../src/deskTypes'
describe('exclusive score bands', () => {
  it('assigns shared edges once, including the final upper endpoint', () => {
    expect([-50, -40, -20, 0, 20, 40, 50].map(scoreBandIndex)).toEqual([0, 1, 2, 3, 4, 5, 5])
    expect(scoreBandIndex(-30)).toBe(1)
    expect(scoreBandIndex(30)).toBe(4)
  })
  it('never marks a missing, invalid or out-of-scale score as current', () => {
    for (const score of [null, undefined, NaN, Infinity, -50.01, 50.01]) expect(scoreBandIndex(score)).toBe(-1)
  })
})
