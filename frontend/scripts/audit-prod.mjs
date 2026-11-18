import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'

const BLOCKING = new Set(['high', 'critical'])
const allowlist = JSON.parse(readFileSync(new URL('../audit-allowlist.json', import.meta.url), 'utf8'))
const allowed = new Set(allowlist.advisories.map((a) => a.id))

let raw
try {
  raw = execFileSync('npm', ['audit', '--omit=dev', '--json'], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
} catch (err) {
  raw = err.stdout
}
if (!raw) {
  console.error('npm audit produced no output')
  process.exit(2)
}
const report = JSON.parse(raw)
if (report.error) {
  console.error('npm audit failed:', report.error.summary || report.error)
  process.exit(2)
}

const blocking = new Map()
const skipped = new Map()
for (const vuln of Object.values(report.vulnerabilities || {})) {
  for (const via of vuln.via || []) {
    if (typeof via !== 'object' || !BLOCKING.has(via.severity)) continue
    const id = (via.url || '').split('/').pop() || String(via.source)
    const line = `${id} ${via.severity} ${via.name}: ${via.title}`
    ;(allowed.has(id) ? skipped : blocking).set(id, line)
  }
}

for (const line of skipped.values()) console.log(`allowlisted: ${line}`)
const unused = [...allowed].filter((id) => !skipped.has(id))
for (const id of unused) console.log(`allowlist entry no longer needed: ${id}`)
if (blocking.size) {
  for (const line of blocking.values()) console.error(`BLOCKING: ${line}`)
  process.exit(1)
}
console.log(`npm audit: no high or critical advisories outside the allowlist (${skipped.size} allowlisted)`)
