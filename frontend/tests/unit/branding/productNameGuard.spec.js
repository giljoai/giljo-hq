import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const SRC = resolve(__dirname, '../../../src')

const FILES = [
  'saas/views/OrgSetupWizard.vue',
  'saas/views/Landing.vue',
  'views/WelcomeView.vue',
  'composables/projectTemplates.js',
]
const DIRS = ['components/setup', 'components/tutorial', 'content/onboarding']

// Company uses that may keep the word "GiljoAI" (none exist in these files today).
const COMPANY_CONTEXT = [/GiljoAI,? (Inc|LLC|Ltd)/, /©\s*\d{4}\s*GiljoAI/, /HOUSE_BRAND/]

function walk(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) return walk(p)
    return /\.(vue|js)$/.test(n) && !/\.spec\./.test(n) && !p.includes('__tests__') ? [p] : []
  })
}

const sources = [
  ...FILES.map((f) => join(SRC, f)),
  ...DIRS.flatMap((d) => walk(join(SRC, d))),
]

describe('product is called Giljo HQ in the wizard, tour, prompts and starter templates', () => {
  it.each(sources.map((p) => [p.replace(SRC + '/', ''), p]))('%s has no person-facing "GiljoAI"', (_n, p) => {
    const offenders = readFileSync(p, 'utf8')
      .split('\n')
      .filter((l) => /Giljo ?AI/.test(l) && !COMPANY_CONTEXT.some((re) => re.test(l)))
    expect(offenders).toEqual([])
  })

  it('tour sentences match the app', () => {
    const t = (f) => readFileSync(join(SRC, f), 'utf8')
    expect(t('components/tutorial/beats/TutorialBeat3.vue')).not.toContain('from Home')
    expect(t('components/tutorial/TutorialRouter.vue')).not.toContain('defined, activated')
    expect(t('components/tutorial/TutorialRouter.vue')).not.toContain('activate when you are ready')
  })
})
