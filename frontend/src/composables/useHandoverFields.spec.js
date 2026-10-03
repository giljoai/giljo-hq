import { describe, it, expect } from 'vitest'
import { HANDOVER_FIELDS, joinHandoverFields, splitHandoverDescription } from './useHandoverFields'

describe('useHandoverFields', () => {
  it('lists the six fields in storage order', () => {
    expect(HANDOVER_FIELDS.map((f) => f.heading)).toEqual([
      '## Where I left off',
      '## Next steps',
      '## Verify before trusting',
      '## Waiting on the operator',
      '## Cannot testify',
      '## References',
    ])
  })

  it('splits an old three-section handover and joins it back unchanged', () => {
    const stored = '## Verify before trusting\n- a\n\n## Waiting on the operator\n- nothing\n\n## Cannot testify\n- b'
    const values = splitHandoverDescription(stored)
    expect(values['please-validate']).toBe('- a')
    expect(values['prior-work']).toBe('')
    expect(joinHandoverFields(values)).toBe(stored)
  })

  it('keeps the old "Where I left off" text and a preamble together in Prior work', () => {
    const values = splitHandoverDescription('Intro line.\n\n## Where I left off\nstopped here')
    expect(values['prior-work']).toBe('Intro line.\n\nstopped here')
  })

  it('keeps text under an unknown heading, heading included, and the text after it', () => {
    const values = splitHandoverDescription('## Cannot testify\n- x\n\n## Misc\nkeep\n\n## References\nr')
    expect(values['unknowns']).toBe('- x')
    expect(values['prior-work']).toBe('## Misc\nkeep')
    expect(values['links']).toBe('r')
  })

  it('does not treat a longer heading as a known one', () => {
    const values = splitHandoverDescription('## Next stepsX\nfoo')
    expect(values['next-steps']).toBe('')
    expect(values['prior-work']).toBe('## Next stepsX\nfoo')
  })

  it('handles empty and missing descriptions', () => {
    expect(joinHandoverFields(splitHandoverDescription(''))).toBe('')
    expect(joinHandoverFields(splitHandoverDescription(null))).toBe('')
  })
})
