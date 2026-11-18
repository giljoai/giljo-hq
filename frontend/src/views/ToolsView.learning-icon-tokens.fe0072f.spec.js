import { describe, expect, it } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'

const src = resolve(__dirname, '..')

function collectDeclared(file, seen = new Set()) {
  if (seen.has(file) || !existsSync(file)) return new Set()
  seen.add(file)
  const text = readFileSync(file, 'utf8')
  const out = new Set([...text.matchAll(/(--[a-z0-9-]+)\s*:/gi)].map((m) => m[1]))
  for (const m of text.matchAll(/@use\s+["']([^"']+)["']/g)) {
    if (m[1].startsWith('sass:')) continue
    const base = resolve(dirname(file), m[1])
    const cand = [base, `${base}.scss`, resolve(dirname(base), `_${base.split('/').pop()}.scss`)]
    const hit = cand.find((c) => c.endsWith('.scss') && existsSync(c))
    if (hit) collectDeclared(hit, seen).forEach((v) => out.add(v))
  }
  return out
}

function loadedTokens() {
  const main = readFileSync(resolve(src, 'main.js'), 'utf8')
  const declared = new Set()
  for (const m of main.matchAll(/import\s+['"]@\/styles\/([^'"]+\.scss)['"]/g)) {
    collectDeclared(resolve(src, 'styles', m[1])).forEach((v) => declared.add(v))
  }
  return declared
}

describe('Tools > Learning card icon tokens', () => {
  const view = readFileSync(resolve(src, 'views/ToolsView.vue'), 'utf8')
  const iconStyles = [...view.matchAll(/class="learning-card-icon"\s+style="([^"]+)"/g)].map((m) => m[1])

  it('finds the four icon wrappers', () => {
    expect(iconStyles).toHaveLength(4)
  })

  it('every --agent-* token on an icon wrapper is declared in the loaded stylesheets', () => {
    const declared = loadedTokens()
    const used = iconStyles.flatMap((s) => [...s.matchAll(/var\((--agent-[a-z0-9-]+)\)/g)].map((m) => m[1]))
    expect(used.length).toBeGreaterThanOrEqual(4)
    const missing = used.filter((t) => !declared.has(t))
    expect(missing).toEqual([])
  })
})
