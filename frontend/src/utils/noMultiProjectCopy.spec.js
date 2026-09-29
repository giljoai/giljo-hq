import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const SRC = join(__dirname, '..')
const SOURCE_FILE = /\.(vue|js|ts|scss|md)$/
const SPEC_FILE = /\.spec\.(js|ts)$/
const RETIRED = /multi[ -]project/i

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) walk(path, out)
    else if (SOURCE_FILE.test(name) && !SPEC_FILE.test(name)) out.push(path)
  }
  return out
}

describe('"Multi project" is gone from the frontend (FE-9655d)', () => {
  it('no source file under src/ uses the retired phrase', () => {
    const hits = []
    for (const file of walk(SRC)) {
      readFileSync(file, 'utf8')
        .split('\n')
        .forEach((line, i) => {
          if (RETIRED.test(line)) hits.push(`${relative(SRC, file)}:${i + 1}: ${line.trim()}`)
        })
    }
    expect(hits).toEqual([])
  })
})
