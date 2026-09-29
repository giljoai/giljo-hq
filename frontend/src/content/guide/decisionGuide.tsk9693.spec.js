import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'

const dir = resolve(__dirname)
const pages = readdirSync(dir).filter((f) => f.endsWith('.md'))

describe('in-app guide names only controls that exist (TSK-9693)', () => {
  it.each(pages)('%s does not mention the retired Auto Check-In slider', (file) => {
    expect(readFileSync(resolve(dir, file), 'utf8')).not.toMatch(/auto check-in/i)
  })

  it('the decision guide points at Check-in cadence under Tools > Agents', () => {
    const guide = readFileSync(resolve(dir, 'decision-guide.md'), 'utf8')
    expect(guide).toMatch(/\*\*Check-in cadence\*\*, under \*\*Tools > Agents\*\*/)
  })
})
