import { computed, reactive, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import {
  REQUIRED_HANDOVER_HEADINGS,
  useHandoverChecklist,
  vanishPlaceholdersOnType,
} from './useHandoverChecklist'

const DEFAULT_TEMPLATE_BODY = REQUIRED_HANDOVER_HEADINGS.map(
  (heading) => `${heading}\n- <fill this in>`,
).join('\n\n')

function checklistFor(text) {
  return useHandoverChecklist(ref(text))
}

describe('useHandoverChecklist', () => {
  it('lists all three headings as missing for an empty description', () => {
    const { items, isComplete } = checklistFor('')
    expect(items.value.map((i) => i.status)).toEqual(['missing', 'missing', 'missing'])
    expect(isComplete.value).toBe(false)
  })

  it('is complete when every heading has real content', () => {
    const text = REQUIRED_HANDOVER_HEADINGS.map((h) => `${h}\n- something real happened here`).join('\n\n')
    const { items, isComplete } = checklistFor(text)
    expect(items.value.every((i) => i.status === 'done')).toBe(true)
    expect(isComplete.value).toBe(true)
  })

  it('flags a heading with nothing under it as empty, not missing', () => {
    const text = [
      '## Verify before trusting',
      '',
      '## Waiting on the operator',
      '- nothing',
      '## Cannot testify',
      '- nothing',
    ].join('\n')
    const { items } = checklistFor(text)
    const verify = items.value.find((i) => i.heading === '## Verify before trusting')
    expect(verify.status).toBe('empty')
  })

  it('treats "nothing" as a real, accepted answer (server parity)', () => {
    const text = REQUIRED_HANDOVER_HEADINGS.map((h) => `${h}\n- nothing`).join('\n\n')
    const { isComplete } = checklistFor(text)
    expect(isComplete.value).toBe(true)
  })

  it('each heading is checked independently (one gap does not hide the others)', () => {
    const text = REQUIRED_HANDOVER_HEADINGS.slice(1)
      .map((h) => `${h}\n- something`)
      .join('\n\n')
    const { incomplete } = checklistFor(text)
    expect(incomplete.value.map((i) => i.heading)).toEqual(['## Verify before trusting'])
  })

  it('an untouched template (all placeholder lines) is NOT complete', () => {
    const { items, isComplete } = checklistFor(DEFAULT_TEMPLATE_BODY)
    expect(items.value.every((i) => i.status === 'placeholder')).toBe(true)
    expect(isComplete.value).toBe(false)
  })

  it('replacing one placeholder section with real text clears only that heading', () => {
    const text = [
      '## Verify before trusting',
      '- checked with `pytest -x`, 12 passed',
      '',
      '## Waiting on the operator',
      '- <fill this in>',
      '',
      '## Cannot testify',
      '- <fill this in>',
    ].join('\n')
    const { items, incomplete } = checklistFor(text)
    expect(items.value.find((i) => i.heading === '## Verify before trusting').status).toBe('done')
    expect(incomplete.value.map((i) => i.heading)).toEqual([
      '## Waiting on the operator',
      '## Cannot testify',
    ])
  })

  it('reacts to a live-updating ref (dialog typing)', () => {
    const description = ref('')
    const { isComplete } = useHandoverChecklist(description)
    expect(isComplete.value).toBe(false)
    description.value = REQUIRED_HANDOVER_HEADINGS.map((h) => `${h}\n- ok`).join('\n\n')
    expect(isComplete.value).toBe(true)
  })

  it('accepts a computed source derived from reactive state, not only a plain ref', () => {
    const state = reactive({ description: DEFAULT_TEMPLATE_BODY })
    const { isComplete } = useHandoverChecklist(computed(() => state.description))
    expect(isComplete.value).toBe(false)
    state.description = REQUIRED_HANDOVER_HEADINGS.map((h) => `${h}\n- ok`).join('\n\n')
    expect(isComplete.value).toBe(true)
  })
})

describe('vanishPlaceholdersOnType', () => {
  it('removes the placeholder line once the user adds a real line below it', () => {
    const oldText = '## Waiting on the operator\n- <fill this in>'
    const newText = '## Waiting on the operator\n- <fill this in>\n- nothing blocked'
    const result = vanishPlaceholdersOnType(oldText, newText)
    expect(result).not.toContain('<fill this in>')
    expect(result).toContain('- nothing blocked')
  })

  it('does nothing once the placeholder is already gone (user selected and typed over it)', () => {
    const oldText = '## Waiting on the operator\n- <fill this in>'
    const newText = '## Waiting on the operator\n- nothing blocked'
    const result = vanishPlaceholdersOnType(oldText, newText)
    expect(result).toBe(newText)
  })

  it('does nothing for a section that was already answered (not a placeholder)', () => {
    const oldText = '## Cannot testify\n- did not check the migration path'
    const newText = '## Cannot testify\n- did not check the migration path, or the rollback'
    const result = vanishPlaceholdersOnType(oldText, newText)
    expect(result).toBe(newText)
  })

  it('leaves other headings alone', () => {
    const oldText = [
      '## Verify before trusting',
      '- <claim> -- check with: <command>',
      '',
      '## Waiting on the operator',
      '- <fill this in>',
    ].join('\n')
    const newText = [
      '## Verify before trusting',
      '- <claim> -- check with: <command>',
      '',
      '## Waiting on the operator',
      '- <fill this in>',
      '- ops needs to rotate the key',
    ].join('\n')
    const result = vanishPlaceholdersOnType(oldText, newText)
    expect(result).toContain('## Verify before trusting\n- <claim> -- check with: <command>')
    expect(result).not.toContain('## Waiting on the operator\n- <fill this in>')
    expect(result).toContain('- ops needs to rotate the key')
  })

  it('handles two headings gaining content in the same edit', () => {
    const oldText = REQUIRED_HANDOVER_HEADINGS.map((h) => `${h}\n- <fill this in>`).join('\n\n')
    const bothAnswered = oldText
      .replace('## Waiting on the operator\n- <fill this in>', '## Waiting on the operator\n- <fill this in>\n- nothing')
      .replace('## Cannot testify\n- <fill this in>', '## Cannot testify\n- <fill this in>\n- nothing')
    const result = vanishPlaceholdersOnType(oldText, bothAnswered)
    expect(result).toContain('## Waiting on the operator\n- nothing')
    expect(result).toContain('## Cannot testify\n- nothing')
    expect(result).toContain('## Verify before trusting\n- <fill this in>')
  })
})
