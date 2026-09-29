/**
 * Every CSS custom property read with var(--name) somewhere in frontend/src
 * must be declared (`--name:`) in a stylesheet or a component <style> block.
 * An undeclared name resolves to nothing (or to its fallback), so the colour
 * the author picked never renders. Vuetify's runtime `--v-*` properties are
 * exempt; names that are only ever set from a JS style binding are listed in
 * SET_FROM_JS; names with no clear owning token yet are in UNOWNED_FALLBACK,
 * each with the fallback it renders today.
 */
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'fs'
import { join, relative, resolve } from 'path'

const SRC = resolve(__dirname, '../../../src')

const SET_FROM_JS = {
  '--jb-edge': 'binding',
  '--nodecol': 'binding',
}

const UNOWNED_FALLBACK = {
  '--bg-terminal': 'fallback',
  '--agent-yellow-primary': 'fallback',
}

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      if (entry === '__tests__') continue
      walk(full, out)
    } else if (/\.(vue|scss|css|js|ts)$/.test(entry) && !/\.spec\.(js|ts)$/.test(entry)) {
      out.push(full)
    }
  }
  return out
}

function scan() {
  const used = new Map()
  const declared = new Set()
  for (const file of walk(SRC)) {
    const text = readFileSync(file, 'utf-8')
    for (const m of text.matchAll(/var\(\s*(--[A-Za-z0-9_-]+)/g)) {
      if (!used.has(m[1])) used.set(m[1], new Set())
      used.get(m[1]).add(relative(SRC, file))
    }
    if (/\.(vue|scss|css)$/.test(file)) {
      for (const m of text.matchAll(/(--[A-Za-z0-9_-]+)\s*:/g)) declared.add(m[1])
    }
  }
  return { used, declared }
}

describe('CSS custom property coverage', () => {
  const { used, declared } = scan()

  it('declares every custom property that frontend/src reads with var()', () => {
    const undeclared = [...used.keys()]
      .filter((name) => !name.startsWith('--v-'))
      .filter((name) => !declared.has(name))
      .filter((name) => !(name in SET_FROM_JS) && !(name in UNOWNED_FALLBACK))
      .sort()
      .map((name) => `${name} <- ${[...used.get(name)].sort().join(', ')}`)
    expect(undeclared).toEqual([])
  })

  it('keeps the allowlists honest: every entry is still read and still undeclared', () => {
    const stale = [...Object.keys(SET_FROM_JS), ...Object.keys(UNOWNED_FALLBACK)].filter(
      (name) => !used.has(name) || declared.has(name),
    )
    expect(stale).toEqual([])
  })

  it('reads the brand yellow through the declared accent token', () => {
    expect(declared.has('--color-accent-primary')).toBe(true)
    expect(used.has('--brand-yellow')).toBe(false)
  })
})
