import { describe, it, expect } from 'vitest'
import { lineDiff } from './lineDiff'

const shape = (rows) => rows.map((r) => `${r.type[0]}:${r.text}`)

describe('lineDiff', () => {
  it('marks a changed line as one removal and one addition, keeping context', () => {
    const rows = lineDiff('a\nb\nc', 'a\nB\nc')
    expect(shape(rows)).toEqual(['s:a', 'r:b', 'a:B', 's:c'])
  })

  it('reports pure additions and pure removals', () => {
    expect(shape(lineDiff('a\nc', 'a\nb\nc'))).toEqual(['s:a', 'a:b', 's:c'])
    expect(shape(lineDiff('a\nb\nc', 'a\nc'))).toEqual(['s:a', 'r:b', 's:c'])
  })

  it('treats an empty side as every line added (or removed)', () => {
    expect(shape(lineDiff('', 'x\ny'))).toEqual(['a:x', 'a:y'])
    expect(shape(lineDiff('x\ny', ''))).toEqual(['r:x', 'r:y'])
    expect(lineDiff('', '')).toEqual([])
  })

  it('tolerates null/undefined and CRLF input', () => {
    expect(shape(lineDiff(null, 'x'))).toEqual(['a:x'])
    expect(shape(lineDiff('a\r\nb', 'a\nb'))).toEqual(['s:a', 's:b'])
  })

  it('keeps line numbers for each side', () => {
    const rows = lineDiff('a\nb', 'a\nx\nb')
    expect(rows[1]).toMatchObject({ type: 'add', text: 'x', oldNo: null, newNo: 2 })
    expect(rows[2]).toMatchObject({ type: 'same', text: 'b', oldNo: 2, newNo: 3 })
  })
})
