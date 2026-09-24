import { computed, unref } from 'vue'

export const REQUIRED_HANDOVER_HEADINGS = Object.freeze([
  '## Verify before trusting',
  '## Waiting on the operator',
  '## Cannot testify',
])

const HEADING_LINE = /^ {0,3}#{1,6}\s/

const PLACEHOLDER_LINE = /^-?\s*<.*>\s*$/

function sectionLines(text, heading) {
  const lines = text.split('\n')
  for (let index = 0; index < lines.length; index += 1) {
    const stripped = lines[index].trim()
    const at = stripped.indexOf(heading)
    if (at === -1) continue

    const body = []
    const trailing = stripped.slice(at + heading.length).replace(/^[ \t:-]+|[ \t:-]+$/g, '')
    if (trailing) body.push(trailing)

    for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
      const following = lines[cursor]
      if (HEADING_LINE.test(following)) break
      if (following.trim()) body.push(following.trim())
    }

    if (body.length > 0) return body
  }
  return []
}

function sectionStatus(text, heading) {
  if (!text.includes(heading)) return 'missing'
  const body = sectionLines(text, heading)
  if (body.length === 0) return 'empty'
  if (body.every((line) => PLACEHOLDER_LINE.test(line))) return 'placeholder'
  return 'done'
}

function removeLineFromSection(text, heading, targetLine) {
  const lines = text.split('\n')
  const headingIndex = lines.findIndex((line) => line.trim() === heading)
  if (headingIndex === -1) return text

  for (let cursor = headingIndex + 1; cursor < lines.length; cursor += 1) {
    if (HEADING_LINE.test(lines[cursor])) break
    if (lines[cursor].trim() === targetLine.trim()) {
      lines.splice(cursor, 1)
      return lines.join('\n')
    }
  }
  return text
}

export function vanishPlaceholdersOnType(oldText, newText) {
  let result = newText
  for (const heading of REQUIRED_HANDOVER_HEADINGS) {
    if (sectionStatus(oldText, heading) !== 'placeholder') continue

    const oldLines = sectionLines(oldText, heading)
    const newLines = sectionLines(result, heading)
    const stillHasAllOldLines = oldLines.every((line) => newLines.includes(line))
    const gainedSomething = newLines.some((line) => !oldLines.includes(line))
    if (!stillHasAllOldLines || !gainedSomething) continue

    for (const placeholderLine of oldLines) {
      result = removeLineFromSection(result, heading, placeholderLine)
    }
  }
  return result
}

export function useHandoverChecklist(descriptionSource) {
  const text = computed(() => unref(descriptionSource) || '')

  const items = computed(() =>
    REQUIRED_HANDOVER_HEADINGS.map((heading) => ({
      heading,
      status: sectionStatus(text.value, heading),
    })),
  )

  const incomplete = computed(() => items.value.filter((item) => item.status !== 'done'))
  const isComplete = computed(() => incomplete.value.length === 0)

  return { items, incomplete, isComplete }
}
