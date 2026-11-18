import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import * as sass from 'sass'

const stylesDir = resolve(__dirname)
const srcDir = resolve(__dirname, '..')
const css = sass.compile(join(stylesDir, '_autofill.scss')).css.replace(/\s+/g, ' ')

const vueFiles = (dir) =>
  readdirSync(dir).flatMap((name) => {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) return name === 'node_modules' ? [] : vueFiles(p)
    return name.endsWith('.vue') ? [p] : []
  })

describe('autofill styling', () => {
  it('hides the resting label when the input is autofilled', () => {
    expect(css).toMatch(
      /\.v-field:has\(input:-webkit-autofill\) \.v-label\.v-field-label \{ visibility: hidden; \}/,
    )
  })

  it('shows the floating label when the input is autofilled', () => {
    expect(css).toMatch(
      /\.v-field:has\(input:-webkit-autofill\) \.v-label\.v-field-label\.v-field-label--floating \{ visibility: unset; \}/,
    )
  })

  it('opens the outlined notch for the floating label', () => {
    expect(css).toMatch(
      /\.v-field:has\(input:-webkit-autofill\)\.v-field--variant-outlined \.v-field__outline__notch::before \{ opacity: 0; \}/,
    )
  })

  it('paints over the browser autofill tint on every field', () => {
    expect(css).toContain('.v-field input:-webkit-autofill,')
    expect(css).toMatch(/-webkit-box-shadow: 0 0 0 1000px rgb\(var\(--v-theme-surface\)\) inset !important/)
  })

  it('is loaded app-wide from main.scss', () => {
    expect(readFileSync(join(stylesDir, 'main.scss'), 'utf8')).toMatch(/^@use "\.\/autofill";$/m)
  })

  it('no view carries its own autofill copy', () => {
    const copies = vueFiles(srcDir).filter((f) => readFileSync(f, 'utf8').includes('-webkit-autofill'))
    expect(copies).toEqual([])
  })
})
