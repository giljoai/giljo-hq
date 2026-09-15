import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const VIEW = readFileSync(resolve(process.cwd(), 'src/views/RoadmapView.vue'), 'utf8')

const stripComments = (src) =>
  src.replace(/<!--[\s\S]*?-->/g, '').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
const CODE = stripComments(VIEW)

describe('RoadmapView — planning only (FE-9555, guarding FE-9568)', () => {
  it('does not wrap the list in SequenceLauncher', () => {
    expect(CODE).not.toMatch(/<SequenceLauncher/)
    expect(CODE).not.toMatch(/SequenceLauncher from/)
  })

  it('renders no "Run sequential" bulk bar', () => {
    expect(CODE).not.toMatch(/SequenceBulkBar/)
    expect(CODE).not.toMatch(/Run sequential/i)
  })

  it('never calls the sequence runner or starts a run', () => {
    expect(CODE).not.toMatch(/useSequenceRunner/)
    expect(CODE).not.toMatch(/startSequence/)
    expect(CODE).not.toMatch(/sequenceRuns\.create/)
  })

  it('never launches or stages a project from this page', () => {
    expect(CODE).not.toMatch(/launch_implementation/)
    expect(CODE).not.toMatch(/prompts\.(staging|implementation|chainStaging)/)
    expect(CODE).not.toMatch(/buildMasterPrompt/)
  })

  it('reads the active-chain store but never writes to it', () => {
    expect(CODE).toMatch(/sequenceRunStore\.isProjectInActiveChain/)
    expect(CODE).not.toMatch(/sequenceRunStore\.(deactivate|release|markReviewed)/)
  })

  it('KEEPS task-to-project promotion (ruling 5 preserves it explicitly)', () => {
    expect(CODE).toMatch(/@convert=/)
    expect(CODE).toMatch(/function convertTask/)
  })

  it('the comment-stripping the scans depend on actually removes comments, and leaves a real file', () => {
    const fixture = '<!-- SequenceLauncher -->\n/* SequenceLauncher */\n// SequenceLauncher\nconst keep = 1\n'
    expect(stripComments(fixture)).not.toMatch(/SequenceLauncher/)
    expect(stripComments(fixture)).toMatch(/const keep = 1/)
    expect(CODE).not.toMatch(/SequenceLauncher/)
    expect(CODE.length).toBeGreaterThan(2000)
    expect(CODE).toMatch(/RoadmapCard/)
  })
})
