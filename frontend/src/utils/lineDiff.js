
const MAX_TABLE_CELLS = 4_000_000

function splitLines(text) {
  if (text === null || text === undefined || text === '') return []
  return String(text).replace(/\r\n?/g, '\n').split('\n')
}

function lcsTable(a, b) {
  const rows = a.length + 1
  const cols = b.length + 1
  const table = new Uint32Array(rows * cols)
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      table[i * cols + j] =
        a[i] === b[j]
          ? table[(i + 1) * cols + j + 1] + 1
          : Math.max(table[(i + 1) * cols + j], table[i * cols + j + 1])
    }
  }
  return { table, cols }
}

export function lineDiff(before, after) {
  const a = splitLines(before)
  const b = splitLines(after)

  let head = 0
  while (head < a.length && head < b.length && a[head] === b[head]) head++
  let tail = 0
  while (
    tail < a.length - head &&
    tail < b.length - head &&
    a[a.length - 1 - tail] === b[b.length - 1 - tail]
  ) {
    tail++
  }

  const rows = []
  for (let k = 0; k < head; k++) rows.push({ type: 'same', text: a[k], oldNo: k + 1, newNo: k + 1 })

  const midA = a.slice(head, a.length - tail)
  const midB = b.slice(head, b.length - tail)
  const { table, cols } =
    (midA.length + 1) * (midB.length + 1) > MAX_TABLE_CELLS
      ? { table: new Uint32Array(0), cols: 0 }
      : lcsTable(midA, midB)
  let i = 0
  let j = 0
  while (i < midA.length || j < midB.length) {
    if (i < midA.length && j < midB.length && midA[i] === midB[j]) {
      rows.push({ type: 'same', text: midA[i], oldNo: head + i + 1, newNo: head + j + 1 })
      i++
      j++
    } else if (
      j >= midB.length ||
      (i < midA.length && (cols === 0 || table[(i + 1) * cols + j] >= table[i * cols + j + 1]))
    ) {
      rows.push({ type: 'remove', text: midA[i], oldNo: head + i + 1, newNo: null })
      i++
    } else {
      rows.push({ type: 'add', text: midB[j], oldNo: null, newNo: head + j + 1 })
      j++
    }
  }

  for (let k = tail; k > 0; k--) {
    rows.push({
      type: 'same',
      text: a[a.length - k],
      oldNo: a.length - k + 1,
      newNo: b.length - k + 1,
    })
  }
  return rows
}
