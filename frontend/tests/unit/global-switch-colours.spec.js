/**
 * The switch colours (faded blue off, green on) come from ONE unscoped
 * `!important` rule set in App.vue, which reaches every v-switch in the app.
 * A scoped copy in a component cannot override it and is not needed.
 *
 * Edition Scope: CE
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const read = (rel) => readFileSync(resolve(__dirname, '../../src', rel), 'utf8')

describe('global switch colours', () => {
  const app = read('App.vue')
  const style = app.slice(app.indexOf('<style'))

  it('App.vue style block is unscoped', () => {
    expect(style.split('\n')[0]).not.toMatch(/scoped/)
  })

  it.each([
    ['.v-switch .v-switch__thumb', 'rgba(33, 150, 243, 0.4)'],
    ['.v-switch .v-switch__track', 'rgba(33, 150, 243, 0.2)'],
    ['.v-switch .v-selection-control--dirty .v-switch__thumb', 'rgb(var(--v-theme-success))'],
    ['.v-switch .v-selection-control--dirty .v-switch__track', 'rgba(76, 175, 80, 0.3)'],
  ])('%s is set with !important', (selector, colour) => {
    const at = style.indexOf(`${selector} {`)
    expect(at).toBeGreaterThan(-1)
    const body = style.slice(at, style.indexOf('}', at))
    expect(body).toContain(`background-color: ${colour} !important`)
  })
})
