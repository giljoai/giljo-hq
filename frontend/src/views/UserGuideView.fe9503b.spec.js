/**
 * UserGuideView.fe9503b.spec.js — FE-9503b
 *
 * The in-app guide gets a new "Driving From Your Terminal" chapter
 * (content/guide/headless-flow.md) describing the harness door alongside
 * the dashboard door.
 *
 * Source-level, not a full mount: UserGuideView.vue statically imports four
 * files under docs/ via `?raw`, and docs/ sits outside vitest's project
 * root — Vite's dev-server fs guard denies that read under test regardless
 * of vi.mock (confirmed: the denial fires before the mock resolves), which
 * is why this view has never had a full-mount unit test. Verifying the
 * import + wiring by source text (same pattern as
 * useActiveProductReconciliation.mount-site.spec.js) proves the chapter is
 * actually wired in without needing docs/ fs access.
 *
 * The chapter content itself is asserted directly against the real file.
 *
 * Edition scope: Both.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const viewSrc = readFileSync(resolve(here, 'UserGuideView.vue'), 'utf8')
const chapterSrc = readFileSync(resolve(here, '../content/guide/headless-flow.md'), 'utf8')

describe('UserGuideView — headless-flow chapter is wired in (FE-9503b)', () => {
  it('imports headless-flow.md', () => {
    expect(/import headlessFlowMd from '\.\.\/content\/guide\/headless-flow\.md\?raw'/.test(viewSrc)).toBe(true)
  })

  it('pushes it into the combined guide markdown', () => {
    expect(/parts\.push\(headlessFlowMd\)/.test(viewSrc)).toBe(true)
  })
})

describe('headless-flow.md — teaches both doors (FE-9503b)', () => {
  it('has a top-level heading the TOC can pick up (## heading)', () => {
    expect(/^## .+$/m.test(chapterSrc)).toBe(true)
  })

  it('describes both the dashboard and the harness/terminal door', () => {
    expect(chapterSrc).toMatch(/dashboard/i)
    expect(chapterSrc).toMatch(/harness|terminal/i)
  })

  it('does not describe a preference toggle (ruling 19: no toggle)', () => {
    expect(chapterSrc.toLowerCase()).not.toMatch(/preference|toggle|switch (on|off)/)
  })
})
