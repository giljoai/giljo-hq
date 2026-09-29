import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('Agent Lab is gone everywhere (TSK-9694)', () => {
  it('the project dialog no longer shows the Agent Lab button', () => {
    const src = readFileSync(resolve(__dirname, 'ProjectCreateEditDialog.vue'), 'utf8')
    expect(src).not.toMatch(/AgentTipsDialog/)
  })

  it('the Agent Lab component itself is removed', () => {
    expect(existsSync(resolve(__dirname, '../common/AgentTipsDialog.vue'))).toBe(false)
  })
})
