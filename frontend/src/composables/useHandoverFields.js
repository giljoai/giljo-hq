
export const HANDOVER_FIELDS = Object.freeze([
  {
    key: 'prior-work',
    label: 'Prior work',
    hint: 'What was done, and where it stopped.',
    heading: '## Where I left off',
  },
  {
    key: 'next-steps',
    label: 'Next steps',
    hint: 'What the next agent should do first.',
    heading: '## Next steps',
  },
  {
    key: 'please-validate',
    label: 'Please validate',
    hint: 'Things the next agent should re-check before relying on them, like "tests pass on branch X".',
    heading: '## Verify before trusting',
  },
  {
    key: 'human-approvals',
    label: 'Human approvals',
    hint: 'Decisions, approvals or access only a person can give. Leave empty if none.',
    heading: '## Waiting on the operator',
  },
  {
    key: 'unknowns',
    label: 'Unknowns',
    hint: 'What you did not check, or what is still unclear.',
    heading: '## Cannot testify',
  },
  {
    key: 'links',
    label: 'Links',
    hint: 'Files, reports or URLs, one per line.',
    heading: '## References',
  },
])

const PRIOR_WORK = HANDOVER_FIELDS[0].key
const HEADING_LINE = /^ {0,3}#{1,6}\s/

export function emptyHandoverValues() {
  return Object.fromEntries(HANDOVER_FIELDS.map((field) => [field.key, '']))
}

function matchKnownHeading(line) {
  const trimmed = line.trim()
  for (const field of HANDOVER_FIELDS) {
    if (!trimmed.startsWith(field.heading)) continue
    const rest = trimmed.slice(field.heading.length)
    if (rest !== '' && !/^[ \t:-]/.test(rest)) continue
    return { field, trailing: rest.replace(/^[ \t:-]+|[ \t:-]+$/g, '') }
  }
  return null
}

export function splitHandoverDescription(description) {
  const chunks = Object.fromEntries(HANDOVER_FIELDS.map((field) => [field.key, []]))
  let current = PRIOR_WORK
  let block = []
  const flush = () => {
    const text = block.join('\n').trim()
    if (text) chunks[current].push(text)
    block = []
  }

  for (const line of String(description || '').split('\n')) {
    const known = matchKnownHeading(line)
    if (known) {
      flush()
      current = known.field.key
      if (known.trailing) block.push(known.trailing)
    } else if (HEADING_LINE.test(line)) {
      flush()
      current = PRIOR_WORK
      block.push(line.trim())
    } else {
      block.push(line)
    }
  }
  flush()

  return Object.fromEntries(HANDOVER_FIELDS.map((field) => [field.key, chunks[field.key].join('\n\n')]))
}

export function joinHandoverFields(values) {
  return HANDOVER_FIELDS.filter((field) => (values[field.key] || '').trim())
    .map((field) => `${field.heading}\n${values[field.key].trim()}`)
    .join('\n\n')
}
