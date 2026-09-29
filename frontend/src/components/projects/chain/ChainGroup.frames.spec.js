import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('ChainGroup step frames', () => {
  const src = readFileSync(resolve(__dirname, 'ChainGroup.vue'), 'utf8')
  const quiet = src.match(/&--quiet\s*\{([^}]*)\}/)
  const current = src.match(/&--current\s*\{([^}]*)\}/)

  it('frames a quiet step in a bright blue-grey ring as heavy as the current one (FE-9686)', () => {
    expect(quiet).not.toBeNull()
    expect(quiet[1]).toMatch(/inset 0 0 0 2px rgba\(\$color-text-hover, 0\.55\)/)
    expect(quiet[1]).not.toMatch(/\$color-border-tertiary|\$color-container-border/)
  })

  it('keeps the current step on the brand yellow ring', () => {
    expect(current[1]).toMatch(/\$color-brand-yellow/)
  })
})
