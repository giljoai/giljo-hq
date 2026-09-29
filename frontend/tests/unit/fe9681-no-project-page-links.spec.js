/**
 * fe9681-no-project-page-links.spec.js — FE-9681
 *
 * The project page (ProjectLaunchView with its Staging and Implementation
 * tabs) is retired. Nothing in src navigates to it any more, and the files
 * only it used are gone. The route name survives solely as a redirect in the
 * router, so a stale bookmark still lands somewhere.
 *
 * Edition scope: Both.
 */
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync, existsSync } from 'node:fs'
import { join, resolve } from 'node:path'

const SRC = resolve(__dirname, '../../src')

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.(vue|js)$/.test(entry) && !/\.spec\.|\.test\./.test(entry)) out.push(full)
  }
  return out
}

const RETIRED = [
  'views/ProjectLaunchView.vue',
  'components/projects/ProjectTabs.vue',
  'components/projects/LaunchTab.vue',
  'components/projects/JobsTab.vue',
  'components/projects/AgentRow.vue',
  'components/projects/chain/ChainMemberLink.vue',
  'components/projects/reviewDispatch.js',
  'composables/useProjectTabsLifecycle.js',
]

describe('the project page is retired (FE-9681)', () => {
  it('no source file navigates to the ProjectLaunch route, except the router redirect', () => {
    const offenders = walk(SRC)
      .filter((file) => !file.endsWith('router/index.js'))
      .filter((file) => /name:\s*'ProjectLaunch'/.test(readFileSync(file, 'utf8')))
      .map((file) => file.replace(SRC + '/', ''))
    expect(offenders).toEqual([])
  })

  it('the files only the page used are gone', () => {
    const present = RETIRED.filter((rel) => existsSync(join(SRC, rel)))
    expect(present).toEqual([])
  })

  it('nothing imports them any more', () => {
    const names = RETIRED.map((rel) => rel.split('/').pop().replace(/\.(vue|js)$/, ''))
    const pattern = new RegExp(`/(${names.join('|')})(\\.vue|\\.js)?'`)
    const offenders = walk(SRC)
      .filter((file) => pattern.test(readFileSync(file, 'utf8')))
      .map((file) => file.replace(SRC + '/', ''))
    expect(offenders).toEqual([])
  })
})
