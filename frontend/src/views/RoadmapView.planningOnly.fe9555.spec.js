/**
 * RoadmapView.planningOnly.fe9555.spec.js — FE-9555
 *
 * /roadmap orders work. It does not launch it.
 *
 * The launch affordances were removed from this page in an earlier change, so
 * these are REGRESSION pins rather than red-first tests: they pass on arrival
 * and exist to stop the wrapper coming back.
 *
 * They are not redundant with RoadmapCard.spec.js, which FE-9568 rewrote to
 * assert the CARD renders no selection checkbox and no Activate/Deactivate. The
 * gap they close is one level up: FE-9568 also removed the SequenceLauncher
 * wrapper that used to enclose the whole list and render the "Run sequential"
 * bulk bar, and nothing guarded the VIEW. A future change could re-wrap the list
 * and every card-level assertion would still pass.
 *
 * The guard was fired on known-bad before being trusted -- see the note on the
 * SequenceLauncher test below.
 *
 * What must NOT be asserted away: task -> project promotion STAYS (ruling 5 keeps
 * it explicitly), so the Convert affordance is pinned PRESENT here. A guard that
 * only ever removes things eventually removes the wrong one.
 *
 * Edition scope: Both.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// Read from the repo path rather than `new URL(..., import.meta.url)`: under the
// jsdom environment `import.meta.url` is not a file: URL, and fileURLToPath throws.
const VIEW = readFileSync(resolve(process.cwd(), 'src/views/RoadmapView.vue'), 'utf8')

/**
 * The view source with comments stripped.
 *
 * Load-bearing: RoadmapView.vue carries a long HTML comment block narrating the
 * FE-6131e -> FE-6176 -> FE-6180 -> FE-9568 history, and it NAMES SequenceLauncher
 * and "Run sequential" several times. A naive source scan matches that history and
 * reports a launch control that is not there. Deleting the history to make a grep
 * simpler would be the wrong trade -- that comment is why the next person does not
 * re-add the wrapper.
 */
const CODE = VIEW.replace(/<!--[\s\S]*?-->/g, '').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')

describe('RoadmapView — planning only (FE-9555, guarding FE-9568)', () => {
  it('does not wrap the list in SequenceLauncher', () => {
    /**
     * Known-bad proof: re-adding `<SequenceLauncher>` around the draggable list
     * and re-running this test was tried, and it failed as intended. An empty
     * match is only a result once the matcher has been shown to bite.
     */
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
    /**
     * The "In chain" pill is a READ-ONLY membership badge that FE-9568 kept
     * deliberately (operator decision), so the store import stays. What must not
     * come back is this page managing membership.
     */
    expect(CODE).toMatch(/sequenceRunStore\.isProjectInActiveChain/)
    expect(CODE).not.toMatch(/sequenceRunStore\.(deactivate|release|markReviewed)/)
  })

  it('KEEPS task-to-project promotion (ruling 5 preserves it explicitly)', () => {
    expect(CODE).toMatch(/@convert=/)
    expect(CODE).toMatch(/function convertTask/)
  })

  it('the comment-stripping the scans depend on actually removes the history block', () => {
    /**
     * Both-sides guard. Every assertion above is a NOT-match over CODE, so a
     * stripper that accidentally emptied the string would make all of them pass
     * against nothing. Assert the raw file still carries the history AND that the
     * stripped source is still a real file.
     */
    expect(VIEW).toMatch(/SequenceLauncher/) // the history comment is still there
    expect(CODE).not.toMatch(/SequenceLauncher/) // and stripping removed exactly it
    expect(CODE.length).toBeGreaterThan(2000)
    expect(CODE).toMatch(/RoadmapCard/)
  })
})
