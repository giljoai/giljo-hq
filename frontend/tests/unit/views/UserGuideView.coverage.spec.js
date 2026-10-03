/**
 * UserGuideView — end-user coverage tests (TSK-8055).
 *
 * Guards the three net-new CE guide chapters that close the rescoped
 * coverage gaps (glossary, chain projects, decision guidance). These
 * chapters live under frontend/src/content/guide/ (not docs/, a protected
 * zone) and ship to public CE.
 *
 * Covers:
 *  1. Each new chapter contributes exactly one `## ` heading (one TOC entry).
 *  2. The glossary defines all ten required terms.
 *  3. Chain coverage uses canonical vocabulary (conductor / linking /
 *     chain mission) and names the real launch control so users can find it.
 *  4. Decision guidance covers project-vs-task and both execution modes.
 *
 * Parallel-safe: no module-level mutable state; content is imported once
 * as static raw markdown.
 */
import { describe, it, expect } from 'vitest'
import decisionGuideMd from '@/content/guide/decision-guide.md?raw'
import chainsMd from '@/content/guide/chains.md?raw'
import glossaryMd from '@/content/guide/glossary.md?raw'

function h2Headings(md) {
  return md
    .split('\n')
    .map((line) => line.match(/^## (.+)$/))
    .filter(Boolean)
    .map((m) => m[1].trim())
}

describe('UserGuideView — new-chapter TOC headings', () => {
  it('decision guide contributes exactly one ## heading', () => {
    expect(h2Headings(decisionGuideMd)).toEqual(['When to Use What'])
  })

  it('chains chapter contributes exactly one ## heading', () => {
    expect(h2Headings(chainsMd)).toEqual(['Chain Projects'])
  })

  it('glossary contributes exactly one ## heading', () => {
    expect(h2Headings(glossaryMd)).toEqual(['Glossary'])
  })
})

describe('UserGuideView — glossary term coverage', () => {
  const REQUIRED_TERMS = [
    'Agent',
    'Orchestrator',
    'Conductor',
    'Project',
    'Job',
    'Task',
    'Product',
    'Chain project',
    '360 Memory',
    'Mission',
  ]

  it.each(REQUIRED_TERMS)('defines the term "%s" in a bold definition cell', (term) => {
    expect(glossaryMd).toContain(`**${term}**`)
  })
})

describe('UserGuideView — chain chapter uses canonical vocabulary', () => {
  it('describes the conductor, linking, and the chain mission', () => {
    expect(chainsMd).toContain('conductor')
    expect(chainsMd.toLowerCase()).toContain('linking')
    expect(chainsMd).toContain('chain mission')
  })

  it('names the real launch control so users can locate it', () => {
    expect(chainsMd).toContain('Run sequential')
  })

  it('states the 2-to-10 project bound', () => {
    expect(chainsMd).toContain('2 to 10 projects')
  })
})

describe('UserGuideView — decision guidance coverage', () => {
  it('covers project vs task', () => {
    expect(decisionGuideMd).toContain('Project or Task?')
  })

  it('covers both execution modes', () => {
    expect(decisionGuideMd).toContain('Multi-Terminal')
    expect(decisionGuideMd).toContain('Subagent')
  })

  it('covers the single-project vs chain decision', () => {
    expect(decisionGuideMd).toContain('One Project or a Chain?')
  })
})
