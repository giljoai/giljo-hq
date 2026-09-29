import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('JobsBoardDetailModal surface', () => {
  const src = readFileSync(resolve(__dirname, 'JobsBoardDetailModal.vue'), 'utf8')
  const rule = src.match(/\.jb-modal-card\s*\{([^}]*)\}/)

  it('has a jb-modal-card style rule', () => {
    expect(rule).not.toBeNull()
  })

  it('paints an opaque surface, not the translucent tertiary background', () => {
    const body = rule[1]
    expect(body).not.toMatch(/\$color-background-tertiary/)
    expect(body).not.toMatch(/rgba\(/)
    expect(body).toMatch(/background:\s*rgb\(var\(--v-theme-surface\)\)/)
  })
})
