import { describe, expect, it } from 'vitest'
import { detailOr } from './detail'

describe('detailOr — the API sentence only when it is a sentence', () => {
  it('passes a string detail through', () => {
    expect(detailOr({ detail: '這個圈子滿了，最多10個人。' }, '加不進來', 409)).toBe('這個圈子滿了，最多10個人。')
  })
  it('never shows an object or a list (the [object Object] the ten-device run found)', () => {
    expect(detailOr({ detail: { error: 'x', open_round: { round_id: 1 } } }, '開不了', 409)).toBe('開不了（409）')
    expect(detailOr({ detail: [{ loc: ['body'], msg: 'field required' }] }, '寫入失敗', 422)).toBe('寫入失敗（422）')
  })
  it('falls back with the status for an empty or missing body', () => {
    expect(detailOr({ detail: '' }, '讀取失敗', 500)).toBe('讀取失敗（500）')
    expect(detailOr({}, '讀取失敗', 502)).toBe('讀取失敗（502）')
    expect(detailOr(null, '讀取失敗', 503)).toBe('讀取失敗（503）')
  })
})
