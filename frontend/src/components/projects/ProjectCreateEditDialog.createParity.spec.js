import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const src = readFileSync(resolve(__dirname, 'ProjectCreateEditDialog.vue'), 'utf8')
const header = src.slice(src.indexOf('<div class="dlg-header">'), src.indexOf('</div>', src.indexOf('<div class="dlg-header">')))
const footer = src.slice(src.indexOf('<div class="dlg-footer'), src.indexOf('Full Mission Text'))

describe('project create dialog matches the task and handover dialogs', () => {
  it('titles the create dialog "Create new Project"', () => {
    expect(src).toContain("'Create new Project'")
    expect(src).not.toContain('Create New Project')
  })

  it('has no icon in the title', () => {
    expect(header).not.toMatch(/dlg-icon/)
    expect(header.replace(/<v-icon>mdi-close<\/v-icon>/, '')).not.toMatch(/<v-icon/)
  })

  it('the primary button says Save for create and edit', () => {
    expect(footer).toMatch(/>\s*Save\s*</)
    expect(footer).not.toMatch(/'Update'|'Create'/)
  })
})
