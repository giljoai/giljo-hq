/**
 * MemoryEntryRow.spec.js — BE-9256 (frontend layer 4).
 *
 * Edition Scope: Both.
 *
 * Stored 360 memory rows can carry a git_commits entry with an empty
 * `message` (legacy bare-SHA normalization, pre-validator). Before this fix
 * the Commits list rendered `{{ commit.message || commit }}`, which fell
 * through to stringifying the raw commit OBJECT for a legacy row (worse
 * than blank — an "[object Object]"-shaped render). The floor: an empty
 * message must render the short SHA as the title text; a titled row is
 * unchanged; a row with no sha keeps today's placeholder (no text after
 * the sha prefix, since there's nothing to show).
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import MemoryEntryRow from '@/components/memory/MemoryEntryRow.vue'

function mountRow(entry, expanded = true) {
  return mount(MemoryEntryRow, {
    props: { entry, expanded, renderedSummary: '<p>summary</p>' },
  })
}

describe('MemoryEntryRow.vue — Commits section legacy-title floor (BE-9256)', () => {
  it('renders the short SHA for a legacy empty-message commit row (never the raw object)', () => {
    const wrapper = mountRow({
      id: 'm1',
      summary: 'x',
      // Legacy row: empty message (pre-validator bare-SHA normalization)
      git_commits: [{ sha: '569905bd0abcdef1234567890', message: '' }],
    })

    const items = wrapper.findAll('.mem-list--mono li')
    expect(items.length).toBe(1)
    const text = items[0].text()
    // The pre-fix template rendered `commit.message || commit`, which for a
    // falsy message fell through to the raw commit OBJECT — toDisplayString
    // JSON-stringifies it, so the buggy render looks like '{"sha":"...",...}'.
    // A correct floor renders exactly the short SHA, nothing else.
    expect(text).not.toContain('{')
    expect(text).not.toContain('"message"')
    expect(text).toBe('569905bd')
  })

  it('renders the real message unchanged for a titled commit row', () => {
    const wrapper = mountRow({
      id: 'm1',
      summary: 'x',
      git_commits: [{ sha: 'aaa1112223334445556667778', message: 'BE-9256: fail-closed validator' }],
    })

    const items = wrapper.findAll('.mem-list--mono li')
    expect(items[0].text()).toContain('BE-9256: fail-closed validator')
  })

  it('keeps today\'s placeholder (no fabricated text) when a commit has no sha at all', () => {
    const wrapper = mountRow({
      id: 'm1',
      summary: 'x',
      git_commits: [{ message: '' }],
    })

    const items = wrapper.findAll('.mem-list--mono li')
    expect(items.length).toBe(1)
    expect(items[0].text()).toBe('')
    expect(items[0].find('.mem-sha').exists()).toBe(false)
  })

  it('does not render the Commits section when git_commits is empty/missing', () => {
    const wrapper = mountRow({ id: 'm1', summary: 'x', git_commits: [] })
    expect(wrapper.find('.mem-list--mono').exists()).toBe(false)
  })
})
