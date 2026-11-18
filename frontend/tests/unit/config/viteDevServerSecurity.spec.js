// SEC-0047: the dev server must not serve files outside the project, must not
// answer other origins, and must bind to loopback unless config.yaml says
// otherwise. The config is loaded with Vite's own loader (the path `npm run dev`
// takes) from a copy in a temp directory, so config.yaml is whatever each case
// writes there and the result never depends on the machine running the test.
import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadConfigFromFile } from 'vite'

const REAL_FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')

let sandbox

async function loadServerConfig(configYaml) {
  const repoRoot = fs.mkdtempSync(path.join(sandbox, 'repo-'))
  const frontendDir = path.join(repoRoot, 'frontend')
  fs.mkdirSync(frontendDir)
  fs.copyFileSync(path.join(REAL_FRONTEND, 'vite.config.js'), path.join(frontendDir, 'vite.config.js'))
  fs.copyFileSync(path.join(REAL_FRONTEND, 'package.json'), path.join(frontendDir, 'package.json'))
  fs.symlinkSync(path.join(REAL_FRONTEND, 'node_modules'), path.join(frontendDir, 'node_modules'), 'dir')
  if (configYaml !== null) {
    fs.writeFileSync(path.join(repoRoot, 'config.yaml'), configYaml)
  }
  const loaded = await loadConfigFromFile(
    { command: 'serve', mode: 'development' },
    path.join(frontendDir, 'vite.config.js'),
    frontendDir,
    'silent',
  )
  return { server: loaded.config.server, repoRoot, frontendDir }
}

function contains(dir, target) {
  const rel = path.relative(dir, target)
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel))
}

describe('vite dev server security (SEC-0047)', () => {
  let noConfig

  beforeAll(async () => {
    sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'sec0047-vite-'))
    noConfig = await loadServerConfig(null)
  })

  afterAll(() => {
    fs.rmSync(sandbox, { recursive: true, force: true })
  })

  it('keeps fs strict mode on', () => {
    expect(noConfig.server.fs?.strict).not.toBe(false)
  })

  it('allows no directory that contains the repo root', () => {
    const { server, repoRoot, frontendDir } = noConfig
    const wide = (server.fs?.allow ?? [])
      .map((entry) => path.resolve(frontendDir, entry))
      .filter((abs) => contains(abs, repoRoot))
    expect(wide).toEqual([])
  })

  it('still allows the frontend and every doc the User Guide imports from ../docs', () => {
    const { server, repoRoot, frontendDir } = noConfig
    const allow = (server.fs?.allow ?? []).map((entry) => path.resolve(frontendDir, entry))
    const guideSource = fs.readFileSync(path.join(REAL_FRONTEND, 'src/views/UserGuideView.vue'), 'utf8')
    const docs = [...guideSource.matchAll(/from '\.\.\/\.\.\/\.\.\/docs\/([^'?]+)\?raw'/g)].map((m) => m[1])
    expect(docs.length).toBeGreaterThan(0)
    const needed = [path.join(frontendDir, 'src', 'main.js'), ...docs.map((doc) => path.join(repoRoot, 'docs', doc))]
    expect(needed.filter((file) => !allow.some((dir) => contains(dir, file)))).toEqual([])
  })

  it('does not open the rest of docs/', () => {
    const { server, repoRoot, frontendDir } = noConfig
    const allow = (server.fs?.allow ?? []).map((entry) => path.resolve(frontendDir, entry))
    expect(allow.some((dir) => contains(dir, path.join(repoRoot, 'docs', 'adr', 'ADR-001.md')))).toBe(false)
  })

  it('does not answer cross-origin readers', () => {
    const { cors } = noConfig.server
    expect(cors).not.toBe(true)
    if (cors && typeof cors === 'object') {
      expect([true, '*']).not.toContain(cors.origin)
    }
  })

  it('binds to loopback when config.yaml is absent', () => {
    expect(noConfig.server.host).toBe('127.0.0.1')
  })

  it('binds to loopback when config.yaml has no dashboard_host', async () => {
    const { server } = await loadServerConfig('server:\n  api_port: 7272\n')
    expect(server.host).toBe('127.0.0.1')
  })

  it('honours a LAN dashboard_host the installer wrote on purpose', async () => {
    const { server } = await loadServerConfig('server:\n  dashboard_host: 192.0.2.40\n  api_port: 7272\n')
    expect(server.host).toBe('192.0.2.40')
  })
})
