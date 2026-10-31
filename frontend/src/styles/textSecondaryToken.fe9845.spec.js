import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { TEXT_SECONDARY } from '@/config/colorTokens'

const read = (f) => readFileSync(resolve(__dirname, f), 'utf8')

describe('secondary text colour token (FE-9845)', () => {
  const tokens = read('design-tokens.scss')
  const main = read('main.scss')

  it('the SCSS token is the design-system value', () => {
    expect(tokens).toMatch(/^\$color-text-secondary:\s*#a3aac4;/m)
  })

  it('the CSS variables are generated from the SCSS token, not retyped', () => {
    expect(main).toMatch(/--color-text-secondary:\s*#\{\$color-text-secondary\};/)
    expect(main).toMatch(/--text-secondary:\s*#\{\$color-text-secondary\};/)
  })

  it('the JS mirror matches', () => {
    expect(TEXT_SECONDARY).toBe('#a3aac4')
  })
})
