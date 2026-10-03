/**
 * A guard around a call that cannot fail teaches readers a failure is
 * handled there. getAgentColor always returns a colour, checkEnhancedStatus
 * always resolves, and a chain header always has its run.
 *
 * Edition scope: Both
 */
import { readFileSync } from 'fs'
import { resolve } from 'path'
import { describe, it, expect } from 'vitest'
import { getAgentColor } from '@/config/agentColors'
import { getAgentBadgeStyle } from '@/utils/colorUtils'

const src = (p) => readFileSync(resolve(__dirname, '../../src', p), 'utf8')

describe('guards around calls that cannot fail are gone', () => {
  it('getAgentColor answers for any name, so the badge helpers read .hex directly', () => {
    expect(getAgentColor('no-such-agent')).toHaveProperty('hex')
    expect(getAgentColor(undefined)).toHaveProperty('hex')
    expect(getAgentBadgeStyle('no-such-agent').color).toBe(getAgentColor('no-such-agent').hex)
    expect(src('utils/colorUtils.js')).not.toMatch(/colorObj\?\.hex/)
    expect(src('components/hub/AgentPill.vue')).not.toMatch(/\)\?\.hex/)
  })

  it('ToolsView reads the edition without a catch around a call that never rejects', () => {
    expect(src('views/ToolsView.vue')).not.toMatch(/try \{\s*\n\s*const status = await setupService\.checkEnhancedStatus\(\)/)
  })

  it('ChainGroupHeader reads run.execution_mode without optional chaining', () => {
    expect(src('components/projects/chain/ChainGroupHeader.vue')).not.toMatch(/chainCtx\.run\?\./)
  })
})
