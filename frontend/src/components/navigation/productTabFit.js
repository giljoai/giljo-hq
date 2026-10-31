
export function planTabFit({ available, widths, gap, fixedWidth, moreWidth, viewedIndex }) {
  const all = widths.map((_, i) => i)
  const total = widths.reduce((sum, w) => sum + w + gap, 0)
  if (available <= 0 || fixedWidth + total <= available) return all

  let used = fixedWidth + moreWidth + gap
  const shown = new Set()
  if (viewedIndex >= 0 && viewedIndex < widths.length) {
    shown.add(viewedIndex)
    used += widths[viewedIndex] + gap
  }
  for (const i of all) {
    if (shown.has(i)) continue
    if (used + widths[i] + gap > available) break
    shown.add(i)
    used += widths[i] + gap
  }
  return all.filter((i) => shown.has(i))
}
